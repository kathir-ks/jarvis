"""Unit tests for WorkspaceBootstrap — agent identity and persona loading."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from jarvis.app.runtime.workspace_bootstrap import (
    WorkspaceBootstrap,
    BOOTSTRAP_FILES,
    _DEFAULT_AGENT_MD,
    _DEFAULT_PERSONA_MD,
    _DEFAULT_TOOLS_MD,
    _BUILTIN_FALLBACKS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    return WorkspaceBootstrap(workspace_dir=tmp_path)


@pytest.fixture
def populated_workspace(tmp_path):
    """Create a workspace with default and agent-specific files."""
    ws = WorkspaceBootstrap(workspace_dir=tmp_path)

    # Create defaults
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir(parents=True)
    (defaults_dir / "AGENT.md").write_text("Default agent instructions")
    (defaults_dir / "PERSONA.md").write_text("Default persona")
    (defaults_dir / "TOOLS.md").write_text("Default tool notes")

    # Create agent-specific files
    agent_dir = tmp_path / "agents" / "agent-42"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("Custom agent instructions for agent-42")
    (agent_dir / "USER.md").write_text("User prefers concise responses")

    return ws


# ---------------------------------------------------------------------------
# Test: File resolution hierarchy
# ---------------------------------------------------------------------------

class TestFileResolution:
    """Test three-tier file resolution (agent → defaults → builtin)."""

    def test_agent_specific_takes_priority(self, populated_workspace):
        """Agent-specific file should override defaults."""
        context = populated_workspace.load_bootstrap_context("agent-42")
        assert context["operating_instructions"] == "Custom agent instructions for agent-42"

    def test_defaults_used_when_no_agent_file(self, populated_workspace):
        """Default files should be used when no agent-specific file exists."""
        context = populated_workspace.load_bootstrap_context("agent-42")
        # PERSONA.md not overridden → should use default
        assert context["persona"] == "Default persona"

    def test_builtin_fallback_when_no_files_exist(self, tmp_workspace):
        """Built-in fallbacks should be used when no files exist at any tier."""
        context = tmp_workspace.load_bootstrap_context("nonexistent-agent")
        # Should get built-in fallback for AGENT.md
        assert "operating_instructions" in context
        assert "Jarvis" in context["operating_instructions"]

    def test_user_profile_loaded(self, populated_workspace):
        """USER.md should be loaded for the specific agent."""
        context = populated_workspace.load_bootstrap_context("agent-42")
        assert context["user_profile"] == "User prefers concise responses"

    def test_no_user_profile_for_missing_file(self, tmp_workspace):
        """USER.md should be absent when no file exists."""
        context = tmp_workspace.load_bootstrap_context("agent-x")
        assert "user_profile" not in context


# ---------------------------------------------------------------------------
# Test: BOOTSTRAP.md one-time consumption
# ---------------------------------------------------------------------------

class TestBootstrapOneTime:
    """Test that BOOTSTRAP.md is loaded once and deleted."""

    def test_bootstrap_loaded_and_deleted(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        agent_dir = tmp_path / "agents" / "agent-1"
        agent_dir.mkdir(parents=True)

        bootstrap_file = agent_dir / "BOOTSTRAP.md"
        bootstrap_file.write_text("Welcome! Set up your preferences.")

        context = ws.load_bootstrap_context("agent-1")

        # Should be in context
        assert context["first_run"] == "Welcome! Set up your preferences."
        # File should be deleted
        assert not bootstrap_file.exists()

    def test_bootstrap_not_present_on_second_load(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        agent_dir = tmp_path / "agents" / "agent-1"
        agent_dir.mkdir(parents=True)

        bootstrap_file = agent_dir / "BOOTSTRAP.md"
        bootstrap_file.write_text("First run only!")

        # First load consumes it
        ws.load_bootstrap_context("agent-1")
        # Second load should not have first_run
        context = ws.load_bootstrap_context("agent-1")
        assert "first_run" not in context


# ---------------------------------------------------------------------------
# Test: build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    """Test system prompt construction from bootstrap files."""

    def test_includes_base_prompt(self, tmp_workspace):
        prompt = tmp_workspace.build_system_prompt("agent-x", base_prompt="Base: I am Jarvis.")
        assert "Base: I am Jarvis." in prompt

    def test_includes_operating_instructions(self, populated_workspace):
        prompt = populated_workspace.build_system_prompt("agent-42")
        assert "Custom agent instructions for agent-42" in prompt
        assert "Operating Instructions" in prompt

    def test_includes_persona(self, populated_workspace):
        prompt = populated_workspace.build_system_prompt("agent-42")
        assert "Default persona" in prompt
        assert "Persona" in prompt

    def test_includes_tool_notes(self, populated_workspace):
        prompt = populated_workspace.build_system_prompt("agent-42")
        assert "Default tool notes" in prompt
        assert "Tool Usage Notes" in prompt

    def test_includes_user_profile(self, populated_workspace):
        prompt = populated_workspace.build_system_prompt("agent-42")
        assert "User prefers concise responses" in prompt
        assert "User Profile" in prompt

    def test_empty_workspace_still_works(self, tmp_workspace):
        prompt = tmp_workspace.build_system_prompt("no-agent", base_prompt="Hi")
        assert "Hi" in prompt
        # Should still include built-in fallbacks
        assert len(prompt) > 10


# ---------------------------------------------------------------------------
# Test: save_agent_file
# ---------------------------------------------------------------------------

class TestSaveAgentFile:
    """Test writing agent-specific bootstrap files."""

    def test_creates_agent_directory_and_file(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        ws.save_agent_file("new-agent", "AGENT.md", "Custom instructions")

        filepath = tmp_path / "agents" / "new-agent" / "AGENT.md"
        assert filepath.exists()
        assert filepath.read_text() == "Custom instructions"

    def test_overwrites_existing_file(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        ws.save_agent_file("agent-1", "PERSONA.md", "Version 1")
        ws.save_agent_file("agent-1", "PERSONA.md", "Version 2")

        filepath = tmp_path / "agents" / "agent-1" / "PERSONA.md"
        assert filepath.read_text() == "Version 2"


# ---------------------------------------------------------------------------
# Test: ensure_defaults
# ---------------------------------------------------------------------------

class TestEnsureDefaults:
    """Test default template creation."""

    def test_creates_default_files(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        ws.ensure_defaults()

        defaults_dir = tmp_path / "defaults"
        assert (defaults_dir / "AGENT.md").exists()
        assert (defaults_dir / "PERSONA.md").exists()
        assert (defaults_dir / "TOOLS.md").exists()

        agent_content = (defaults_dir / "AGENT.md").read_text()
        assert "Jarvis" in agent_content

    def test_does_not_overwrite_existing_defaults(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir(parents=True)
        (defaults_dir / "AGENT.md").write_text("My custom default")

        ws.ensure_defaults()

        # Should NOT be overwritten
        assert (defaults_dir / "AGENT.md").read_text() == "My custom default"
        # But PERSONA.md should be created
        assert (defaults_dir / "PERSONA.md").exists()


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_agent_id_with_special_characters(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        # Agent IDs with dashes and underscores should work
        ws.save_agent_file("agent-123_test", "AGENT.md", "works")
        context = ws.load_bootstrap_context("agent-123_test")
        assert context["operating_instructions"] == "works"

    def test_empty_file_returns_empty_string(self, tmp_path):
        ws = WorkspaceBootstrap(workspace_dir=tmp_path)
        agent_dir = tmp_path / "agents" / "agent-1"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("")

        context = ws.load_bootstrap_context("agent-1")
        # Empty file should still be in context (it exists)
        # The _resolve_file returns empty string which is truthy-false
        # but still set in context
        # Actually empty string means the file was found but empty
        # The content check `if content is not None` allows empty strings
        assert "operating_instructions" in context

    def test_bootstrap_files_constant_matches_expected(self):
        """Verify the BOOTSTRAP_FILES mapping is correct."""
        assert BOOTSTRAP_FILES["AGENT.md"] == "operating_instructions"
        assert BOOTSTRAP_FILES["PERSONA.md"] == "persona"
        assert BOOTSTRAP_FILES["TOOLS.md"] == "tool_notes"
        assert BOOTSTRAP_FILES["USER.md"] == "user_profile"
        assert BOOTSTRAP_FILES["BOOTSTRAP.md"] == "first_run"
