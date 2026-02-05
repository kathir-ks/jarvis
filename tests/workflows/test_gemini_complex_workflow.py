"""
Test 5: Multi-Tool Complex Workflow

Validates:
- Orchestration of multiple tools in sequence
- Complex multi-step reasoning
- Tool result integration
- Coherent final synthesis
"""
import pytest
from jarvis.app.runtime.agent_runner import AgentRunner
from .conftest import run_workflow, assert_tool_usage, assert_response_quality


@pytest.mark.asyncio
async def test_comprehensive_workflow(agent_runner: AgentRunner):
    """
    Test comprehensive workflow using multiple tools.

    Workflow: Time → Calculation → Web search → Code execution
    Expected: 4-5 different tools used, coherent synthesis
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "What time is it? Calculate hours until midnight. "
            "Search for 'productivity tips' and write a Python script "
            "to print the top productivity tip you found."
        ),
        timeout=120.0,  # Longer timeout for complex workflow
    )

    # Assert minimum tool usage (at least 3 different tools)
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    assert len(called_tools) >= 3, (
        f"Expected at least 3 different tools, got {len(called_tools)}: {called_tools}"
    )

    # Verify specific tools were likely used
    expected_any = ["get_time", "calculator", "web_search", "execute_code"]
    tools_found = [tool for tool in expected_any if tool in called_tools]
    assert len(tools_found) >= 3, (
        f"Expected at least 3 tools from {expected_any}, got {tools_found}"
    )

    # Assert response quality
    assert_response_quality(
        result,
        min_length=100,
    )

    # Assert reasonable iteration count (6-10 for complex workflow)
    assert result["iterations"] >= 3, "Expected at least 3 iterations for complex workflow"
    assert result["iterations"] <= 12, "Too many iterations for workflow"

    print(f"\n✓ Comprehensive workflow completed in {result['duration']:.2f}s")
    print(f"  Unique tools used: {len(called_tools)} - {called_tools}")
    print(f"  Total tool calls: {len(tool_calls)}")
    print(f"  Iterations: {result['iterations']}")
    print(f"  Response: {result['response'][:200]}...")


@pytest.mark.asyncio
async def test_research_and_compute_workflow(agent_runner: AgentRunner):
    """
    Test workflow combining research and computation.

    Workflow: Search for data → Extract numbers → Calculate statistics
    Expected: web_search and calculator/execute_code tools
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Search for 'world population 2026' and calculate the "
            "percentage increase from 2020 (assume 2020 population was 7.8 billion)"
        ),
        timeout=90.0,
    )

    # Assert tool usage
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    # Should use search and calculation
    assert len(called_tools) >= 2, f"Expected at least 2 tools, got {called_tools}"

    # Assert response quality
    assert_response_quality(
        result,
        min_length=50,
        should_contain=["population"],
    )

    print(f"\n✓ Research and compute workflow completed in {result['duration']:.2f}s")
    print(f"  Tools used: {called_tools}")
    print(f"  Response: {result['response'][:150]}...")


@pytest.mark.asyncio
async def test_time_based_task_workflow(agent_runner: AgentRunner):
    """
    Test workflow with time-based calculations and code generation.

    Workflow: Get time → Calculate time difference → Generate reminder code
    Expected: get_time, calculator, execute_code tools
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Get current time, calculate seconds until 2 hours from now, "
            "and write a Python script that would wait that many seconds "
            "(don't actually execute the wait, just show the code)"
        ),
        timeout=60.0,
    )

    # Assert tool usage
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    # Should use get_time and at least one of calculator/execute_code
    assert "get_time" in called_tools, "Expected get_time tool to be used"
    assert len(called_tools) >= 2, f"Expected at least 2 tools, got {called_tools}"

    # Assert response quality (should mention code or time calculation)
    assert_response_quality(
        result,
        min_length=50,
    )

    print(f"\n✓ Time-based task workflow completed in {result['duration']:.2f}s")
    print(f"  Tools used: {called_tools}")
    print(f"  Response: {result['response'][:150]}...")


@pytest.mark.asyncio
async def test_iterative_problem_solving_workflow(agent_runner: AgentRunner):
    """
    Test iterative problem solving with multiple tool invocations.

    Workflow: Research → Calculate → Verify → Report
    Expected: Multiple iterations, multiple tools
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Calculate the factorial of 10, then search online to verify "
            "if your calculation is correct, then write code to calculate "
            "factorial of 15 and execute it"
        ),
        timeout=90.0,
    )

    # Assert tool usage
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    # Should use calculator/execute_code and web_search
    assert len(called_tools) >= 2, f"Expected at least 2 different tools, got {called_tools}"

    # Assert response quality
    assert_response_quality(
        result,
        min_length=50,
        should_contain=["factorial"],
    )

    print(f"\n✓ Iterative problem solving completed in {result['duration']:.2f}s")
    print(f"  Tools used: {called_tools}")
    print(f"  Total tool calls: {len(tool_calls)}")
    print(f"  Response: {result['response'][:200]}...")


@pytest.mark.asyncio
async def test_multi_domain_workflow(agent_runner: AgentRunner):
    """
    Test workflow spanning multiple domains (time, math, web, code).

    Workflow: Complex task requiring orchestration across all tool types
    Expected: All major tool categories used
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Tell me the current time and day of week. "
            "If it's a weekday, calculate 8 hours from now. "
            "If it's weekend, search for 'weekend productivity tips'. "
            "Then write a short Python script to greet me based on the time of day."
        ),
        timeout=120.0,
    )

    # Assert tool usage
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    # Should use at least 3 different tools
    assert len(called_tools) >= 3, (
        f"Expected at least 3 different tools, got {len(called_tools)}: {called_tools}"
    )

    # Assert response quality
    assert_response_quality(
        result,
        min_length=100,
    )

    print(f"\n✓ Multi-domain workflow completed in {result['duration']:.2f}s")
    print(f"  Tools used: {called_tools}")
    print(f"  Total tool calls: {len(tool_calls)}")
    print(f"  Iterations: {result['iterations']}")
    print(f"  Response length: {len(result['response'])} chars")
