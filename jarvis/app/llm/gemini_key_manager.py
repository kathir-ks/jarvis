"""Gemini API key rotation manager for multi-account free tier usage.

Tracks per-key, per-model request counts and automatically rotates
to the next available key when limits are hit.  Usage state is
persisted to a JSON file so it survives process restarts and resets
daily (aligned with Google's free-tier quota window).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = Path(__file__).resolve().parents[3] / ".gemini_key_state.json"


class GeminiKeyExhaustedError(Exception):
    """Raised when all API keys have exhausted their quota."""


class GeminiKeyManager:
    """Round-robin manager for multiple Gemini API keys.

    Parameters
    ----------
    api_keys : list[str]
        One or more Gemini API keys.
    requests_per_key_per_model : int
        Max requests allowed per key per model before rotation (default 20).
    max_models_per_key : int
        Max distinct models a single key may address per day (default 3).
    state_file : str | Path | None
        Path used for persisting usage counters across restarts.
        Set to ``None`` to disable persistence.
    """

    def __init__(
        self,
        api_keys: list[str],
        requests_per_key_per_model: int = 20,
        max_models_per_key: int = 3,
        state_file: str | Path | None = _DEFAULT_STATE_FILE,
    ) -> None:
        if not api_keys:
            raise ValueError("At least one Gemini API key is required.")

        self._keys = list(api_keys)
        self._rpm = requests_per_key_per_model
        self._max_models = max_models_per_key
        self._state_file = Path(state_file) if state_file else None
        self._lock = threading.Lock()

        # usage[key_index][model] = count
        self._usage: dict[int, dict[str, int]] = {i: {} for i in range(len(self._keys))}
        self._reset_date: str = date.today().isoformat()

        self._load_state()
        logger.info(
            "GeminiKeyManager initialised: %d key(s), %d req/key/model, %d models/key",
            len(self._keys),
            self._rpm,
            self._max_models,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_key(self, model: str) -> str:
        """Return the best available API key for *model*.

        Selection strategy:
        1. Skip keys that have hit the per-model request limit.
        2. Skip keys that have hit the max-models cap and haven't used *model* before.
        3. Among remaining keys, pick the one with the fewest requests for *model*
           (least-used first) to distribute load evenly.

        Raises ``GeminiKeyExhaustedError`` when no key is available.
        """
        with self._lock:
            self._check_daily_reset()

            best_idx: int | None = None
            best_count: int = self._rpm + 1  # sentinel

            for idx in range(len(self._keys)):
                model_counts = self._usage[idx]
                count = model_counts.get(model, 0)

                # Already hit limit for this model
                if count >= self._rpm:
                    continue

                # Would exceed model diversity cap
                if model not in model_counts and len(model_counts) >= self._max_models:
                    continue

                if count < best_count:
                    best_count = count
                    best_idx = idx

            if best_idx is None:
                raise GeminiKeyExhaustedError(
                    f"All {len(self._keys)} Gemini key(s) exhausted for model '{model}'. "
                    "Quota resets daily.  Add more keys via JARVIS_GEMINI_API_KEYS."
                )

            logger.debug(
                "Selected key #%d for model=%s (used %d/%d)",
                best_idx,
                model,
                best_count,
                self._rpm,
            )
            return self._keys[best_idx]

    def record_usage(self, api_key: str, model: str) -> None:
        """Increment the request counter for *api_key* + *model*."""
        with self._lock:
            self._check_daily_reset()
            try:
                idx = self._keys.index(api_key)
            except ValueError:
                logger.warning("record_usage called with unknown key (ignored)")
                return

            self._usage[idx].setdefault(model, 0)
            self._usage[idx][model] += 1

            logger.debug(
                "Key #%d model=%s usage now %d/%d",
                idx,
                model,
                self._usage[idx][model],
                self._rpm,
            )
            self._save_state()

    def mark_exhausted(self, api_key: str, model: str) -> None:
        """Force-mark a key as exhausted for *model* (e.g. on HTTP 429)."""
        with self._lock:
            try:
                idx = self._keys.index(api_key)
            except ValueError:
                return
            self._usage[idx][model] = self._rpm
            logger.info("Key #%d force-exhausted for model=%s", idx, model)
            self._save_state()

    def get_status(self) -> list[dict[str, Any]]:
        """Return a human-readable status snapshot of all keys."""
        with self._lock:
            self._check_daily_reset()
            status = []
            for idx in range(len(self._keys)):
                masked = self._keys[idx][:8] + "..." + self._keys[idx][-4:]
                models = self._usage[idx]
                total_used = sum(models.values())
                total_capacity = self._rpm * self._max_models
                status.append({
                    "key_index": idx,
                    "key_masked": masked,
                    "models_used": len(models),
                    "max_models": self._max_models,
                    "per_model_usage": dict(models),
                    "requests_per_model_limit": self._rpm,
                    "total_used": total_used,
                    "total_capacity": total_capacity,
                    "remaining": total_capacity - total_used,
                })
            return status

    @property
    def total_capacity(self) -> int:
        """Total requests possible across all keys and models."""
        return len(self._keys) * self._rpm * self._max_models

    @property
    def total_remaining(self) -> int:
        """Approximate remaining requests across all keys."""
        with self._lock:
            self._check_daily_reset()
            used = sum(
                sum(models.values())
                for models in self._usage.values()
            )
            return self.total_capacity - used

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _check_daily_reset(self) -> None:
        """Reset all counters if the calendar day has changed."""
        today = date.today().isoformat()
        if today != self._reset_date:
            logger.info("Daily quota reset (was %s, now %s)", self._reset_date, today)
            self._reset_date = today
            self._usage = {i: {} for i in range(len(self._keys))}
            self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        if not self._state_file:
            return
        try:
            payload = {
                "reset_date": self._reset_date,
                "usage": {str(k): v for k, v in self._usage.items()},
            }
            self._state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Failed to save key-manager state", exc_info=True)

    def _load_state(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            saved_date = raw.get("reset_date", "")

            # Only restore if same day
            if saved_date == date.today().isoformat():
                saved_usage = raw.get("usage", {})
                for str_idx, model_counts in saved_usage.items():
                    idx = int(str_idx)
                    if idx < len(self._keys):
                        self._usage[idx] = model_counts
                self._reset_date = saved_date
                logger.info("Restored key-manager state from %s", self._state_file)
            else:
                logger.info("Stale key-manager state (date=%s) — starting fresh", saved_date)
        except Exception:
            logger.debug("Failed to load key-manager state", exc_info=True)
