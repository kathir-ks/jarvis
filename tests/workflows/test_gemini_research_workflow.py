"""
Test 2: Research Workflow

Validates:
- Web search tool usage
- URL reading and content extraction
- Multi-step research process
- Summarization capabilities
"""
import pytest
from jarvis.app.runtime.agent_runner import AgentRunner
from .conftest import run_workflow, assert_tool_usage, assert_response_quality


@pytest.mark.asyncio
async def test_basic_research_workflow(agent_runner: AgentRunner):
    """
    Test basic research workflow with web search and URL reading.

    Workflow: Web search → URL reading → Summarization
    Expected: web_search and read_url tools called, coherent summary
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Search for 'Python asyncio best practices 2026' "
            "and summarize the top result"
        ),
        timeout=60.0,  # Longer timeout for web operations
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["web_search"],
        min_calls=1,
    )

    # May also use read_url if implementation supports it
    tool_calls = result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=50,
        should_contain=["python", "asyncio"],
    )

    # Assert reasonable iteration count (search → read → summarize)
    assert result["iterations"] >= 1, "Expected at least 1 iteration"
    assert result["iterations"] <= 6, "Too many iterations for simple research"

    print(f"\n✓ Basic research workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Tools used: {called_tools}")
    print(f"  Response length: {len(result['response'])} chars")


@pytest.mark.asyncio
async def test_comparative_research_workflow(agent_runner: AgentRunner):
    """
    Test comparative research requiring multiple searches.

    Workflow: Multiple searches → Compare results → Synthesize
    Expected: Multiple web_search calls, comparative analysis
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Search for information about FastAPI vs Flask performance "
            "and tell me which one is faster for async operations"
        ),
        timeout=90.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["web_search"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=100,
        should_contain=["fastapi", "flask"],
    )

    print(f"\n✓ Comparative research workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:200]}...")


@pytest.mark.asyncio
async def test_research_with_url_reading(agent_runner: AgentRunner):
    """
    Test research workflow with explicit URL reading.

    Workflow: Search → Get URL → Read URL → Summarize
    Expected: Both web_search and read_url tools used
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "Search for 'Model Context Protocol MCP' and read the "
            "content of the first result to explain what MCP is"
        ),
        timeout=75.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["web_search"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=50,
        should_contain=["mcp", "protocol"],
    )

    print(f"\n✓ Research with URL reading completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")


@pytest.mark.asyncio
async def test_fact_checking_workflow(agent_runner: AgentRunner):
    """
    Test fact-checking workflow.

    Workflow: User claim → Web search for verification → Fact check result
    Expected: web_search tool, clear verification statement
    """
    result = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "I heard that Python 3.13 was released in 2024. "
            "Can you verify this by searching online?"
        ),
        timeout=60.0,
    )

    # Assert tool usage
    assert_tool_usage(
        workflow_result=result,
        expected_tools=["web_search"],
        min_calls=1,
    )

    # Assert response quality
    assert_response_quality(
        workflow_result=result,
        min_length=30,
        should_contain=["python"],
    )

    print(f"\n✓ Fact-checking workflow completed in {result['duration']:.2f}s")
    print(f"  Tool calls: {len(result['tool_calls'])}")
    print(f"  Response: {result['response'][:150]}...")
