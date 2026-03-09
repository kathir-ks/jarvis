"""Unit tests for core tools — execute_code, calculator, get_time."""
from __future__ import annotations

import pytest

from jarvis.app.llm.tools.core_tools import (
    execute_code_handler,
    get_time_handler,
    calculator_handler,
    EXECUTE_CODE_TOOL,
    GET_TIME_TOOL,
    CALCULATOR_TOOL,
)


# ---------------------------------------------------------------------------
# Test: Calculator
# ---------------------------------------------------------------------------

class TestCalculator:
    """Test the calculator tool handler."""

    @pytest.mark.asyncio
    async def test_basic_arithmetic(self):
        result = await calculator_handler({"expression": "2 + 3"})
        assert result["success"] is True
        assert result["result"] == 5

    @pytest.mark.asyncio
    async def test_multiplication(self):
        result = await calculator_handler({"expression": "6 * 7"})
        assert result["success"] is True
        assert result["result"] == 42

    @pytest.mark.asyncio
    async def test_division(self):
        result = await calculator_handler({"expression": "100 / 4"})
        assert result["success"] is True
        assert result["result"] == 25.0

    @pytest.mark.asyncio
    async def test_sqrt(self):
        result = await calculator_handler({"expression": "sqrt(16)"})
        assert result["success"] is True
        assert result["result"] == 4.0

    @pytest.mark.asyncio
    async def test_trigonometry(self):
        result = await calculator_handler({"expression": "sin(0)"})
        assert result["success"] is True
        assert result["result"] == 0.0

    @pytest.mark.asyncio
    async def test_pi_constant(self):
        result = await calculator_handler({"expression": "pi"})
        assert result["success"] is True
        assert abs(result["result"] - 3.14159) < 0.001

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        result = await calculator_handler({"expression": "undefined_var + 1"})
        assert result["success"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_expression_preserved_in_result(self):
        result = await calculator_handler({"expression": "2 ** 10"})
        assert result["expression"] == "2 ** 10"
        assert result["result"] == 1024

    @pytest.mark.asyncio
    async def test_factorial(self):
        result = await calculator_handler({"expression": "factorial(5)"})
        assert result["success"] is True
        assert result["result"] == 120


# ---------------------------------------------------------------------------
# Test: Get Time
# ---------------------------------------------------------------------------

class TestGetTime:
    """Test the get_time tool handler."""

    @pytest.mark.asyncio
    async def test_iso_format(self):
        result = await get_time_handler({"format": "iso"})
        assert "formatted" in result
        assert "T" in result["formatted"]  # ISO format contains T

    @pytest.mark.asyncio
    async def test_unix_format(self):
        result = await get_time_handler({"format": "unix"})
        assert isinstance(result["formatted"], int)
        assert result["formatted"] > 0

    @pytest.mark.asyncio
    async def test_human_format(self):
        result = await get_time_handler({"format": "human"})
        assert "formatted" in result
        assert "-" in result["formatted"]  # YYYY-MM-DD format

    @pytest.mark.asyncio
    async def test_default_format(self):
        result = await get_time_handler({})
        assert "iso" in result
        assert "unix" in result

    @pytest.mark.asyncio
    async def test_timezone_field(self):
        result = await get_time_handler({"timezone": "UTC"})
        assert result["timezone"] == "UTC"


# ---------------------------------------------------------------------------
# Test: Execute Code
# ---------------------------------------------------------------------------

class TestExecuteCode:
    """Test the execute_code tool handler."""

    @pytest.mark.asyncio
    async def test_simple_print(self):
        result = await execute_code_handler({"code": "print('hello')"})
        assert result["success"] is True
        assert "hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_math_computation(self):
        result = await execute_code_handler({"code": "print(sum(range(10)))"})
        assert result["success"] is True
        assert "45" in result["stdout"]

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        result = await execute_code_handler({"code": "def incomplete("})
        assert result["success"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_runtime_error(self):
        result = await execute_code_handler({"code": "1/0"})
        assert result["success"] is False
        assert "ZeroDivision" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_capped(self):
        """Timeout should be capped at 30 seconds."""
        result = await execute_code_handler({
            "code": "print('quick')",
            "timeout": 999,
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_import_access(self):
        """Code shouldn't be able to import arbitrary modules."""
        result = await execute_code_handler({"code": "import os\nprint(os.getcwd())"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Test: Tool definitions
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    """Test tool metadata definitions."""

    def test_calculator_definition(self):
        assert CALCULATOR_TOOL.name == "calculator"
        assert len(CALCULATOR_TOOL.parameters) == 1
        assert CALCULATOR_TOOL.parameters[0].name == "expression"
        assert CALCULATOR_TOOL.parameters[0].required is True

    def test_get_time_definition(self):
        assert GET_TIME_TOOL.name == "get_time"
        assert len(GET_TIME_TOOL.parameters) == 2

    def test_execute_code_definition(self):
        assert EXECUTE_CODE_TOOL.name == "execute_code"
        assert EXECUTE_CODE_TOOL.parameters[0].name == "code"
        assert EXECUTE_CODE_TOOL.timeout_seconds == 35
