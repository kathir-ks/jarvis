"""Tests for the Circuit Breaker and retry utilities.

Covers:
- Circuit state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Failure threshold triggering
- Recovery timeout
- Call wrapper
- Exponential backoff retry
- Timeout wrapper
"""
import asyncio
import pytest
from unittest.mock import AsyncMock

from jarvis.app.runtime.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    retry_with_backoff,
    with_timeout,
)


class TestCircuitBreaker:

    @pytest.fixture
    def breaker(self):
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout_seconds=1.0,  # Short for testing
        )

    def test_initial_state_is_closed(self, breaker):
        assert breaker.get_state("agent_1") == CircuitState.CLOSED
        assert breaker.can_call("agent_1") is True

    def test_stays_closed_below_threshold(self, breaker):
        breaker.record_failure("agent_1")
        breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.CLOSED
        assert breaker.can_call("agent_1") is True

    def test_opens_at_threshold(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.OPEN
        assert breaker.can_call("agent_1") is False

    def test_success_resets_consecutive_failures(self, breaker):
        breaker.record_failure("agent_1")
        breaker.record_failure("agent_1")
        breaker.record_success("agent_1")
        breaker.record_failure("agent_1")
        breaker.record_failure("agent_1")
        # Should still be closed — consecutive count reset
        assert breaker.get_state("agent_1") == CircuitState.CLOSED

    def test_open_blocks_calls(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        assert breaker.can_call("agent_1") is False

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        assert breaker.can_call("agent_1") is True
        assert breaker.get_state("agent_1") == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        await asyncio.sleep(1.1)

        # Trigger half-open transition
        breaker.can_call("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.HALF_OPEN

        breaker.record_success("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        await asyncio.sleep(1.1)

        breaker.can_call("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.HALF_OPEN

        breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.OPEN

    def test_independent_circuits_per_agent(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.OPEN
        assert breaker.get_state("agent_2") == CircuitState.CLOSED

    def test_manual_reset(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.OPEN

        breaker.reset("agent_1")
        assert breaker.get_state("agent_1") == CircuitState.CLOSED
        assert breaker.get_stats("agent_1").consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_call_wrapper_success(self, breaker):
        fn = AsyncMock(return_value="ok")
        result = await breaker.call("agent_1", fn, "arg1", key="val")
        assert result == "ok"
        fn.assert_called_once_with("arg1", key="val")
        assert breaker.get_stats("agent_1").successes == 1

    @pytest.mark.asyncio
    async def test_call_wrapper_failure(self, breaker):
        fn = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await breaker.call("agent_1", fn)
        assert breaker.get_stats("agent_1").failures == 1

    @pytest.mark.asyncio
    async def test_call_wrapper_circuit_open_raises(self, breaker):
        for _ in range(3):
            breaker.record_failure("agent_1")

        fn = AsyncMock()
        with pytest.raises(CircuitOpenError):
            await breaker.call("agent_1", fn)
        fn.assert_not_called()

    def test_get_summary(self, breaker):
        breaker.record_success("agent_1")
        breaker.record_failure("agent_2")

        summary = breaker.get_summary()
        assert "agent_1" in summary
        assert summary["agent_1"]["state"] == "closed"
        assert "agent_2" in summary


class TestRetryWithBackoff:

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        fn = AsyncMock(return_value="ok")
        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        fn = AsyncMock(side_effect=[RuntimeError("fail"), RuntimeError("fail"), "ok"])
        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_exhausted_retries(self):
        fn = AsyncMock(side_effect=RuntimeError("permanent"))
        with pytest.raises(RuntimeError, match="permanent"):
            await retry_with_backoff(fn, max_retries=2, base_delay=0.01)
        assert fn.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        fn = AsyncMock(side_effect=ValueError("wrong type"))
        with pytest.raises(ValueError, match="wrong type"):
            await retry_with_backoff(
                fn,
                max_retries=3,
                base_delay=0.01,
                retry_on=(RuntimeError,),
            )
        assert fn.call_count == 1  # No retry for ValueError


class TestWithTimeout:

    @pytest.mark.asyncio
    async def test_completes_within_timeout(self):
        async def fast():
            return 42
        result = await with_timeout(fast(), timeout_seconds=1.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        async def slow():
            await asyncio.sleep(10)
        with pytest.raises(TimeoutError, match="timed out"):
            await with_timeout(slow(), timeout_seconds=0.05, error_message="timed out")
