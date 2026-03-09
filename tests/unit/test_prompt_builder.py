"""Unit tests for PromptBuilder — system prompt construction and memory integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jarvis.app.runtime.agent import Agent, AgentConfig, AgentStatus, AgentType
from jarvis.app.llm.prompt_builder import PromptBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    agent_id: str = "test-agent",
    short_term_memory: list | None = None,
    context: dict | None = None,
) -> Agent:
    """Create a minimal Agent for prompt builder tests."""
    return Agent(
        _id=agent_id,
        user_id="test-user",
        agent_type=AgentType.MASTER,
        status=AgentStatus.RUNNING,
        config=AgentConfig(),
        short_term_memory=short_term_memory or [],
        context=context or {},
    )


# ---------------------------------------------------------------------------
# Test: build_agent_messages uses workspace bootstrap
# ---------------------------------------------------------------------------

class TestBuildAgentMessagesWithBootstrap:
    """Test that build_agent_messages integrates workspace bootstrap."""

    def test_system_prompt_includes_workspace_content(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = (
                "Base prompt\n## Operating Instructions\nDo things well."
            )
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent()

            messages = builder.build_agent_messages(
                agent,
                {"content": "Hello"},
            )

            # Should call workspace bootstrap
            mock_ws.build_system_prompt.assert_called_once_with(
                agent_id="test-agent",
                base_prompt=PromptBuilder.BASE_SYSTEM_PROMPT,
            )

            # System message should contain workspace content
            assert messages[0]["role"] == "system"
            assert "Operating Instructions" in messages[0]["content"]

    def test_user_message_is_last(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = "System prompt"
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent()

            messages = builder.build_agent_messages(
                agent,
                {"content": "What is 2+2?"},
            )

            assert messages[-1]["role"] == "user"
            assert messages[-1]["content"] == "What is 2+2?"


# ---------------------------------------------------------------------------
# Test: Short-term memory summarization
# ---------------------------------------------------------------------------

class TestShortTermMemory:
    """Test short-term memory formatting."""

    def test_includes_recent_memory(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = "System"
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent(short_term_memory=[
                {"role": "user", "content": "What is Python?", "timestamp": "2026-01-01"},
                {"role": "assistant", "content": "Python is a programming language.", "timestamp": "2026-01-01"},
            ])

            messages = builder.build_agent_messages(agent, {"content": "Tell me more"})

            # Should have a system message with memory
            memory_msgs = [m for m in messages if "conversation history" in m.get("content", "").lower()]
            assert len(memory_msgs) == 1
            assert "Python" in memory_msgs[0]["content"]

    def test_truncates_long_content(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = "System"
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            long_content = "x" * 500
            agent = _make_agent(short_term_memory=[
                {"role": "assistant", "content": long_content, "timestamp": "2026-01-01"},
            ])

            messages = builder.build_agent_messages(agent, {"content": "?"})
            memory_msgs = [m for m in messages if "conversation history" in m.get("content", "").lower()]
            # Content should be truncated with "..."
            assert "..." in memory_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Test: Long-term context formatting
# ---------------------------------------------------------------------------

class TestLongTermContext:
    """Test long-term memory context formatting."""

    def test_includes_interactions_and_discoveries(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = "System"
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent()

            long_term = {
                "interactions": [
                    {"content": "Previous conversation about ML", "score": 0.85},
                ],
                "discoveries": [
                    {"content": "Found article about transformers", "metadata": {"source": "arxiv"}},
                ],
                "knowledge": [
                    {"content": "User prefers Python", "metadata": {"knowledge_type": "preference", "confidence": 0.9}},
                ],
            }

            messages = builder.build_agent_messages(agent, {"content": "test"}, long_term_context=long_term)

            # Should have long-term memory system message
            lt_msgs = [m for m in messages if "long-term memory" in m.get("content", "").lower()]
            assert len(lt_msgs) == 1
            assert "Previous conversation about ML" in lt_msgs[0]["content"]
            assert "transformers" in lt_msgs[0]["content"]
            assert "Python" in lt_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Test: Delegation messages
# ---------------------------------------------------------------------------

class TestDelegationMessages:
    """Test delegation-specific prompt building."""

    def test_includes_parent_task_and_sibling_results(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.side_effect = lambda **kw: kw.get("base_prompt", "System")
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent(agent_id="sub-agent-1")

            delegation_context = {
                "parent_task_description": "Research machine learning trends",
                "subtask_description": "Find recent papers on transformers",
                "subtask_index": 1,
                "total_subtasks": 3,
                "parent_short_term_summary": "User asked about ML research",
                "parent_session_context": {"topic": "machine learning"},
                "sibling_results": [
                    {
                        "capability": "web_research",
                        "status": "completed",
                        "output_summary": "Found 5 papers on attention mechanisms",
                    },
                ],
            }

            messages = builder.build_delegation_messages(agent, delegation_context)

            # Check system messages
            all_content = " ".join(m["content"] for m in messages if m["role"] == "system")
            assert "specialized sub-agent" in all_content
            assert "Research machine learning trends" in all_content
            assert "ML research" in all_content
            assert "attention mechanisms" in all_content

            # User message should be the subtask
            assert messages[-1]["role"] == "user"
            assert "transformers" in messages[-1]["content"]

    def test_delegation_without_sibling_results(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap") as mock_ws_fn, \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            mock_ws = MagicMock()
            mock_ws.build_system_prompt.return_value = "System"
            mock_ws_fn.return_value = mock_ws

            builder = PromptBuilder()
            agent = _make_agent()

            delegation_context = {
                "parent_task_description": "Simple task",
                "subtask_description": "Do the thing",
                "subtask_index": 0,
                "total_subtasks": 1,
                "parent_short_term_summary": "",
                "parent_session_context": {},
                "sibling_results": [],
            }

            messages = builder.build_delegation_messages(agent, delegation_context)

            # Should still have system + user messages
            assert len(messages) >= 2
            assert messages[-1]["content"] == "Do the thing"

            # Should NOT have sibling results section
            all_content = " ".join(m["content"] for m in messages)
            assert "Prior Subtasks" not in all_content


# ---------------------------------------------------------------------------
# Test: _format_incoming
# ---------------------------------------------------------------------------

class TestFormatIncoming:
    """Test incoming message normalization."""

    def test_simple_text_message(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap"), \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            builder = PromptBuilder()
            result = builder._format_incoming({"content": "Hello", "type": "message"})
            assert result == "Hello"

    def test_message_with_metadata(self):
        with patch("jarvis.app.llm.prompt_builder.get_workspace_bootstrap"), \
             patch("jarvis.app.llm.prompt_builder.get_token_counter"), \
             patch("jarvis.app.llm.prompt_builder.get_memory_selector"):
            builder = PromptBuilder()
            result = builder._format_incoming({
                "content": "Search this",
                "type": "task",
                "metadata": {"priority": "high"},
            })
            assert "Search this" in result
            assert "task" in result
            assert "priority=high" in result
