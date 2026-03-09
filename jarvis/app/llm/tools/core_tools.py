"""Core system and utility tools for agent capabilities."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone
import math
import os
import sys
import tempfile

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
_MAX_OUTPUT_BYTES = 64 * 1024


async def execute_code_handler(params: dict[str, Any]) -> dict[str, Any]:
    """Execute Python code in an isolated subprocess with stripped environment."""
    import asyncio

    code = params["code"]
    timeout = min(params.get("timeout", 10), 30)  # Cap at 30 seconds

    logger.info("Executing code in subprocess (timeout=%ds)", timeout)

    try:
        # Write code to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name

        # Minimal env — strips all secrets / credentials
        env = {"PATH": os.environ.get("PATH", "")}

        proc = await asyncio.create_subprocess_exec(
            sys.executable, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "success": False,
                "stdout": "",
                "stderr": None,
                "error": f"Code execution timed out after {timeout}s",
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
        success = proc.returncode == 0

        result = {
            "success": success,
            "stdout": stdout_text,
            "stderr": stderr_text if stderr_text else None,
            "error": stderr_text if not success else None,
        }

        logger.info("Code execution completed: success=%s", success)
        return result

    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": None,
            "error": f"{type(e).__name__}: {str(e)}",
        }


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
