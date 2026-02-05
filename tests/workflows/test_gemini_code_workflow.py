"""
Test 3: Code Generation & Execution Workflow

Validates:
- Code generation capabilities
- Code execution via execute_code tool
- Error handling and retry logic
- Result interpretation
"""
import pytest
from jarvis.app.runtime.agent_runner import AgentRunner
from .conftest import run_workflow, assert_tool_usage, assert_response_quality


@pytest.mark.asyncio
async def test_fibonacci_generation_workflow(agent_runner: AgentRunner):
    """
    Test code generation and execution for Fibonacci sequence.

    Workflow: Generate code → Execute → Explain result
    Expected: execute_code tool called, correct Fibonacci sequence
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Write Python code to calculate the first 10 Fibonacci numbers "
            "and execute it"
        ),
        timeout=45.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["execute_code"],
        min_calls=1,
    )

    # Assert response quality (should mention Fibonacci or show the sequence)
    assert_response_quality(
        workflow_result=result,
        min_length=30,
        should_contain=["fibonacci"],
    )

    # Assert reasonable iteration count
    assert result["iterations"] >= 1, "Expected at least 1 iteration"
    assert result["iterations"] <= 5, "Too many iterations for simple code execution"

    print(f"\n✓ Fibonacci code workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Iterations: {result['iterations']}")
    print(f"  Response: {result['response'][:150]}...")


@pytest.mark.asyncio
async def test_data_processing_workflow(agent_runner: AgentRunner):
    """
    Test code generation for data processing.

    Workflow: Generate data processing code → Execute → Report results
    Expected: execute_code tool, correct statistical results
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Write Python code to calculate the mean, median, and standard deviation "
            "of this list: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]. Execute it."
        ),
        timeout=45.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["execute_code"],
        min_calls=1,
    )

    # Assert response quality (should mention mean=55)
    assert_response_quality(
        workflow_result=result,
        min_length=30,
        should_contain=["55"],  # Mean of 10-100 by tens is 55
    )

    print(f"\n✓ Data processing workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:150]}...")


@pytest.mark.asyncio
async def test_code_with_error_recovery(agent_runner: AgentRunner):
    """
    Test code generation with potential error and recovery.

    Workflow: User requests complex task → Agent generates code →
              Executes (may fail) → Fixes → Re-executes
    Expected: execute_code may be called multiple times
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Write code to create a function that checks if a number is prime, "
            "then test it with numbers 17, 18, 19, 20. Execute the code."
        ),
        timeout=60.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["execute_code"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=30,
        should_contain=["17", "19"],  # Prime numbers in the test set
    )

    print(f"\n✓ Code with error recovery completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:200]}...")


@pytest.mark.asyncio
async def test_code_visualization_workflow(agent_runner: AgentRunner):
    """
    Test code generation for creating visualizations (text-based).

    Workflow: Generate plotting code → Execute → Describe output
    Expected: execute_code tool, description of visualization
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Write Python code to create a simple text-based bar chart "
            "for the data: {'A': 5, 'B': 10, 'C': 7, 'D': 12}. Execute it."
        ),
        timeout=45.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["execute_code"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=20,
    )

    print(f"\n✓ Code visualization workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")


@pytest.mark.asyncio
async def test_algorithm_implementation_workflow(agent_runner: AgentRunner):
    """
    Test algorithm implementation and testing.

    Workflow: Implement algorithm → Test with examples → Verify correctness
    Expected: execute_code tool, correct algorithm results
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Implement binary search algorithm in Python and test it by "
            "searching for the number 42 in the sorted list [10, 20, 30, 42, 50, 60]. "
            "Execute the code."
        ),
        timeout=50.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["execute_code"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=30,
        should_contain=["42"],
    )

    print(f"\n✓ Algorithm implementation workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:150]}...")
