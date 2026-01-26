"""Core system and utility tools for agent capabilities."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone
import json
import sys
from io import StringIO
import math

from ..tool_registry import (
    ToolDefinition,
    ToolParameter,
    ToolCategory,
    ToolRegistry,
    get_tool_registry,
)

logger = logging.getLogger(__name__)


# Tool Definitions
EXECUTE_CODE_TOOL = ToolDefinition(
    name="execute_code",
    description="Execute Python code safely in a restricted environment. Returns the output and any errors.",
    category=ToolCategory.CODE,
    parameters=[
        ToolParameter(
            name="code",
            type="string",
            description="The Python code to execute",
            required=True,
        ),
        ToolParameter(
            name="timeout",
            type="number",
            description="Execution timeout in seconds (max 30)",
            required=False,
            default=10,
        ),
    ],
    returns="object",
    returns_description="Object with stdout, stderr, and success fields",
    timeout_seconds=35,
)


GET_TIME_TOOL = ToolDefinition(
    name="get_time",
    description="Get the current date and time in various formats. Useful for time-aware tasks.",
    category=ToolCategory.SYSTEM,
    parameters=[
        ToolParameter(
            name="format",
            type="string",
            description="Output format",
            required=False,
            default="iso",
            enum=["iso", "unix", "human"],
        ),
        ToolParameter(
            name="timezone",
            type="string",
            description="Timezone (e.g., 'UTC', 'America/New_York')",
            required=False,
            default="UTC",
        ),
    ],
    returns="object",
    returns_description="Object with formatted time information",
    timeout_seconds=1,
)


CALCULATOR_TOOL = ToolDefinition(
    name="calculator",
    description="Evaluate mathematical expressions safely. Supports basic arithmetic, trigonometry, and common functions.",
    category=ToolCategory.DATA,
    parameters=[
        ToolParameter(
            name="expression",
            type="string",
            description="Mathematical expression to evaluate (e.g., '2 + 2', 'sin(pi/2)', 'sqrt(16)')",
            required=True,
        ),
    ],
    returns="object",
    returns_description="Object with result and the expression evaluated",
    timeout_seconds=5,
)


# Tool Handlers
async def execute_code_handler(params: dict[str, Any]) -> dict[str, Any]:
    """Execute Python code in a restricted environment."""
    code = params["code"]
    timeout = min(params.get("timeout", 10), 30)  # Cap at 30 seconds

    logger.info("Executing code (timeout=%ds)", timeout)

    # Capture stdout and stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    success = False
    error_msg = None

    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Create restricted globals (no file I/O, no imports except safe ones)
        safe_globals = {
            "__builtins__": {
                # Safe built-ins only
                "abs": abs,
                "all": all,
                "any": any,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "float": float,
                "int": int,
                "len": len,
                "list": list,
                "max": max,
                "min": min,
                "print": print,
                "range": range,
                "round": round,
                "set": set,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
                "zip": zip,
                # Math module
                "math": math,
            }
        }

        # Execute with timeout
        import asyncio

        def _exec():
            exec(code, safe_globals)

        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _exec),
            timeout=timeout
        )

        success = True

    except asyncio.TimeoutError:
        error_msg = f"Code execution timed out after {timeout}s"
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()

    result = {
        "success": success,
        "stdout": stdout_text,
        "stderr": stderr_text if stderr_text else None,
        "error": error_msg,
    }

    logger.info("Code execution completed: success=%s", success)
    return result


async def get_time_handler(params: dict[str, Any]) -> dict[str, Any]:
    """Get current time in various formats."""
    format_type = params.get("format", "iso")
    tz_str = params.get("timezone", "UTC")

    logger.info("Getting time: format=%s, tz=%s", format_type, tz_str)

    now = datetime.now(timezone.utc)

    # For simplicity, we'll just use UTC
    # In production, you'd use pytz or zoneinfo for proper timezone handling
    if tz_str != "UTC":
        logger.warning("Non-UTC timezones not fully supported yet, using UTC")

    result = {
        "timezone": tz_str,
        "iso": now.isoformat(),
        "unix": int(now.timestamp()),
    }

    if format_type == "iso":
        result["formatted"] = now.isoformat()
    elif format_type == "unix":
        result["formatted"] = int(now.timestamp())
    elif format_type == "human":
        result["formatted"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    else:
        result["formatted"] = now.isoformat()

    return result


async def calculator_handler(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate mathematical expressions safely."""
    expression = params["expression"]

    logger.info("Evaluating expression: %s", expression)

    try:
        # Safe math evaluation - only allow math operations
        safe_dict = {
            # Math functions
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            # Math module
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "asin": math.asin,
            "acos": math.acos,
            "atan": math.atan,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
            "floor": math.floor,
            "ceil": math.ceil,
            "factorial": math.factorial,
        }

        result = eval(expression, {"__builtins__": {}}, safe_dict)

        return {
            "success": True,
            "expression": expression,
            "result": result,
            "error": None,
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.warning("Calculator error: %s", error_msg)

        return {
            "success": False,
            "expression": expression,
            "result": None,
            "error": error_msg,
        }


def register_core_tools(registry: ToolRegistry | None = None) -> None:
    """Register all core system tools."""
    registry = registry or get_tool_registry()

    registry.register(EXECUTE_CODE_TOOL, execute_code_handler)
    registry.register(GET_TIME_TOOL, get_time_handler)
    registry.register(CALCULATOR_TOOL, calculator_handler)

    logger.info("Core tools registered")
