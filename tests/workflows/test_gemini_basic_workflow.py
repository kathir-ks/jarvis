"""
Test 1: Basic Calculation Workflow

Validates:
- Single tool call (calculator)
- Simple request-response flow
- Correct result processing
"""
import pytest
from jarvis.app.runtime.agent_runner import AgentRunner
from .conftest import run_workflow, assert_tool_usage, assert_response_quality


@pytest.mark.asyncio
async def test_basic_calculation_workflow(agent_runner: AgentRunner):
    """
    Test basic calculation workflow.

    Workflow: User message → Tool call → Result processing
    Expected: Single calculator call, correct answer (36)
    """
    # Run workflow
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content="Calculate sqrt(256) + 10 * 2",
        timeout=30.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["calculator"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=10,
        should_contain=["36"],  # sqrt(256) = 16, 10*2 = 20, 16+20 = 36
    )

    # Assert iterations (should be 2: request tool → process result → respond)
    assert result["iterations"] >= 1, "Expected at least 1 iteration"
    assert result["iterations"] <= 3, "Expected at most 3 iterations"

    # Assert duration (should be quick)
    assert result["duration"] < 15.0, f"Workflow took too long: {result['duration']}s"

    print(f"\n✓ Basic calculation workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Iterations: {result['iterations']}")
    print(f"  Response: {result['response'][:100]}...")


@pytest.mark.asyncio
async def test_multiple_calculations_workflow(agent_runner: AgentRunner):
    """
    Test multiple sequential calculations.

    Workflow: User message → Multiple tool calls → Combined result
    Expected: Multiple calculator calls, all correct
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Calculate the following step by step: "
            "1) 25 * 4, "
            "2) sqrt of the result from step 1, "
            "3) add 50 to the result from step 2"
        ),
        timeout=45.0,
    )

    # Assert tool usage (may call calculator multiple times)
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["calculator"],
        min_calls=1,  # At least one call
    )

    # Assert response contains correct final answer (sqrt(100) + 50 = 10 + 50 = 60)
    assert_response_quality(
        workflow_result=result,
        min_length=20,
        should_contain=["60"],
    )

    print(f"\n✓ Multiple calculations workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:150]}...")


@pytest.mark.asyncio
async def test_calculation_with_time_workflow(agent_runner: AgentRunner):
    """
    Test calculation combined with time tool.

    Workflow: Get time → Calculate hours until midnight
    Expected: get_time and calculator tools used
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content="What time is it now? Calculate how many hours until midnight.",
        timeout=30.0,
    )

    # Assert both tools used
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["get_time", "calculator"],
        min_calls=2,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=20,
        should_contain=["hours"],
    )

    print(f"\n✓ Time + calculation workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
