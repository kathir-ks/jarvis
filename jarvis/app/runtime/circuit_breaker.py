"""
Circuit Breaker for Agent Communication

Prevents cascading failures when delegating work to sub-agents.
If an agent consistently fails, the circuit trips open and
subsequent calls fail fast instead of wasting resources.

States:
    CLOSED  → normal operation, calls pass through
    OPEN    → agent is failing, calls rejected immediately
    HALF_OPEN → testing recovery, one call allowed through

Includes:
- Per-agent circuit state
- Configurable failure threshold and recovery timeout
- Exponential backoff retry wrapper for delegations
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Circuit state
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitStats:
    """Failure/success counters for a single circuit."""
    failures: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_calls: int = 0

    def record_success(self) -> None:
        self.successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.monotonic()
        self.total_calls += 1

    def record_failure(self) -> None:
        self.failures += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        self.total_calls += 1

    def reset(self) -> None:
        self.failures = 0
        self.successes = 0
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.last_success_time = 0.0
        self.total_calls = 0


@dataclass
class AgentCircuit:
    """Circuit breaker state for a single agent."""
    agent_id: str
    state: CircuitState = CircuitState.CLOSED
    stats: CircuitStats = field(default_factory=CircuitStats)
    opened_at: float = 0.0  # monotonic time when circuit opened

    @property
    def failure_rate(self) -> float:
        if self.stats.total_calls == 0:
            return 0.0
        return self.stats.failures / self.stats.total_calls


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Circuit breaker for agent-to-agent communication.

    Tracks per-agent failure rates and trips the circuit open when
    an agent exceeds the failure threshold. After a recovery timeout,
    allows a single test call (half-open). If that succeeds, the circuit
    resets to closed.

    Usage:
        breaker = CircuitBreaker()

        # Check before delegating
        if not breaker.can_call(agent_id):
            # Choose a different agent or fail fast
            ...

        # Record outcomes
        breaker.record_success(agent_id)
        breaker.record_failure(agent_id)

        # Or use the call wrapper
        result = await breaker.call(agent_id, my_async_fn, *args)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        """
        Args:
            failure_threshold: Consecutive failures before tripping open.
            recovery_timeout_seconds: Seconds to wait in OPEN before trying HALF_OPEN.
            half_open_max_calls: Calls allowed in HALF_OPEN before deciding.
        """
        self._circuits: dict[str, AgentCircuit] = {}
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self.half_open_max_calls = half_open_max_calls

    def _get_circuit(self, agent_id: str) -> AgentCircuit:
        if agent_id not in self._circuits:
            self._circuits[agent_id] = AgentCircuit(agent_id=agent_id)
        return self._circuits[agent_id]

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def can_call(self, agent_id: str) -> bool:
        """
        Check whether a call to the agent is allowed.

        Returns:
            True if the circuit is CLOSED or has transitioned to HALF_OPEN.
        """
        circuit = self._get_circuit(agent_id)
        now = time.monotonic()

        if circuit.state == CircuitState.CLOSED:
            return True

        if circuit.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if now - circuit.opened_at >= self.recovery_timeout:
                circuit.state = CircuitState.HALF_OPEN
                logger.info(
                    "Circuit for agent %s transitioning to HALF_OPEN "
                    "(was open for %.1fs)",
                    agent_id, now - circuit.opened_at,
                )
                return True
            return False

        if circuit.state == CircuitState.HALF_OPEN:
            # Allow limited calls in half-open
            return True

        return False

    def get_state(self, agent_id: str) -> CircuitState:
        """Get current circuit state for an agent."""
        return self._get_circuit(agent_id).state

    def get_stats(self, agent_id: str) -> CircuitStats:
        """Get failure/success statistics for an agent."""
        return self._get_circuit(agent_id).stats

    # ------------------------------------------------------------------
    # Recording outcomes
    # ------------------------------------------------------------------

    def record_success(self, agent_id: str) -> None:
        """Record a successful call to an agent."""
        circuit = self._get_circuit(agent_id)
        circuit.stats.record_success()

        if circuit.state == CircuitState.HALF_OPEN:
            # Recovery confirmed — close the circuit
            circuit.state = CircuitState.CLOSED
            circuit.stats.consecutive_failures = 0
            logger.info(
                "Circuit for agent %s CLOSED (recovered after half-open test)",
                agent_id,
            )

    def record_failure(self, agent_id: str) -> None:
        """Record a failed call to an agent."""
        circuit = self._get_circuit(agent_id)
        circuit.stats.record_failure()

        if circuit.state == CircuitState.HALF_OPEN:
            # Failed during recovery test — reopen
            circuit.state = CircuitState.OPEN
            circuit.opened_at = time.monotonic()
            logger.warning(
                "Circuit for agent %s re-OPENED (failed during half-open test)",
                agent_id,
            )
            return

        if (
            circuit.state == CircuitState.CLOSED
            and circuit.stats.consecutive_failures >= self.failure_threshold
        ):
            circuit.state = CircuitState.OPEN
            circuit.opened_at = time.monotonic()
            logger.warning(
                "Circuit for agent %s OPENED after %d consecutive failures",
                agent_id, circuit.stats.consecutive_failures,
            )

    def reset(self, agent_id: str) -> None:
        """Reset circuit to CLOSED with fresh stats."""
        circuit = self._get_circuit(agent_id)
        circuit.state = CircuitState.CLOSED
        circuit.stats.reset()
        circuit.opened_at = 0.0
        logger.info("Circuit for agent %s manually reset", agent_id)

    # ------------------------------------------------------------------
    # Call wrapper
    # ------------------------------------------------------------------

    async def call(
        self,
        agent_id: str,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute an async function with circuit breaker protection.

        Raises CircuitOpenError if the circuit is open.
        Records success/failure automatically.

        Args:
            agent_id: Target agent.
            fn: Async function to execute.
            *args, **kwargs: Passed to fn.

        Returns:
            Return value of fn.
        """
        if not self.can_call(agent_id):
            raise CircuitOpenError(agent_id, self.get_stats(agent_id))

        try:
            result = await fn(*args, **kwargs)
            self.record_success(agent_id)
            return result
        except Exception:
            self.record_failure(agent_id)
            raise

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all circuit states."""
        return {
            agent_id: {
                "state": circuit.state.value,
                "consecutive_failures": circuit.stats.consecutive_failures,
                "total_calls": circuit.stats.total_calls,
                "failure_rate": round(circuit.failure_rate, 3),
            }
            for agent_id, circuit in self._circuits.items()
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit."""

    def __init__(self, agent_id: str, stats: CircuitStats):
        self.agent_id = agent_id
        self.stats = stats
        super().__init__(
            f"Circuit open for agent {agent_id} "
            f"(consecutive_failures={stats.consecutive_failures})"
        )


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

async def retry_with_backoff(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        fn: Async function to call.
        *args: Positional arguments for fn.
        max_retries: Maximum retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap.
        backoff_factor: Multiplier for each retry.
        retry_on: Exception types that trigger retry.
        **kwargs: Keyword arguments for fn.

    Returns:
        Return value of fn on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retry_on as exc:
            last_exc = exc
            if attempt >= max_retries:
                break

            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            logger.warning(
                "Attempt %d/%d failed: %s — retrying in %.1fs",
                attempt + 1, max_retries + 1, exc, delay,
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Delegation timeout wrapper
# ---------------------------------------------------------------------------

async def with_timeout(
    coro: Awaitable[T],
    timeout_seconds: float,
    error_message: str = "Operation timed out",
) -> T:
    """
    Execute a coroutine with a timeout.

    Args:
        coro: Coroutine to execute.
        timeout_seconds: Maximum seconds to wait.
        error_message: Message for TimeoutError.

    Returns:
        Result of the coroutine.

    Raises:
        TimeoutError: If timeout_seconds is exceeded.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise TimeoutError(error_message)
