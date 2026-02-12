"""
Workspace Bootstrap System

Inspired by OpenClaw's workspace-first approach, this module provides agent identity
and persona management through Markdown bootstrap files.

Bootstrap files give each agent a persistent identity, operating instructions, and
persona that survives across sessions. This is analogous to OpenClaw's AGENTS.md,
SOUL.md, TOOLS.md, and USER.md pattern.

Directory layout:
    workspace/
    ├── defaults/              # Default templates for new agents
    │   ├── AGENT.md           # Default operating instructions
    │   ├── PERSONA.md         # Default persona/tone/boundaries
    │   └── TOOLS.md           # Default tool usage notes
    └── agents/
        └── {agent_id}/
            ├── AGENT.md       # Agent-specific operating instructions
            ├── PERSONA.md     # Agent-specific persona
            ├── TOOLS.md       # Agent-specific tool notes
            ├── USER.md        # User profile context
            └── BOOTSTRAP.md   # One-time first-run instructions (deleted after)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default workspace location (relative to project root)
DEFAULT_WORKSPACE_DIR = "workspace"

# Bootstrap file names and their roles
BOOTSTRAP_FILES = {
    "AGENT.md": "operating_instructions",
    "PERSONA.md": "persona",
    "TOOLS.md": "tool_notes",
    "USER.md": "user_profile",
    "BOOTSTRAP.md": "first_run",
}


class WorkspaceBootstrap:
    """Loads agent identity and persona from workspace Markdown files.

    Provides a three-tier resolution for each file:
    1. Agent-specific: workspace/agents/{agent_id}/FILE.md
    2. Defaults: workspace/defaults/FILE.md
    3. Built-in fallback: hardcoded minimal content

    The BOOTSTRAP.md file is special — it's loaded once on first run and then deleted,
    allowing one-time initialization rituals.
    """

    def __init__(self, workspace_dir: str | Path | None = None):
        """Initialize workspace bootstrap.

        Args:
            workspace_dir: Path to workspace directory. Defaults to ./workspace.
        """
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir)
        else:
            self.workspace_dir = Path(DEFAULT_WORKSPACE_DIR)

    def load_bootstrap_context(self, agent_id: str) -> dict[str, str]:
        """Load all bootstrap files for an agent.

        Resolves each file through the three-tier hierarchy (agent → defaults → builtin).

        Args:
            agent_id: The agent ID.

        Returns:
            Dict mapping role names to content strings:
            {
                "operating_instructions": "...",
                "persona": "...",
                "tool_notes": "...",
                "user_profile": "...",
                "first_run": "..." or None,
            }
        """
        context: dict[str, str] = {}
        agent_dir = self.workspace_dir / "agents" / agent_id
        defaults_dir = self.workspace_dir / "defaults"

        for filename, role in BOOTSTRAP_FILES.items():
            content = self._resolve_file(filename, agent_dir, defaults_dir)
            if content is not None:
                context[role] = content

        # Handle BOOTSTRAP.md — load and delete (one-time)
        bootstrap_file = agent_dir / "BOOTSTRAP.md"
        if bootstrap_file.exists():
            try:
                context["first_run"] = bootstrap_file.read_text(encoding="utf-8")
                bootstrap_file.unlink()
                logger.info(f"Loaded and consumed BOOTSTRAP.md for agent {agent_id}")
            except Exception as e:
                logger.warning(f"Failed to process BOOTSTRAP.md for agent {agent_id}: {e}")

        logger.info(
            f"Loaded bootstrap context for agent {agent_id}: "
            f"{list(context.keys())}"
        )

        return context

    def build_system_prompt(
        self,
        agent_id: str,
        base_prompt: str = "",
    ) -> str:
        """Build a complete system prompt by combining bootstrap files with a base prompt.

        Args:
            agent_id: The agent ID.
            base_prompt: Optional base system prompt to prepend.

        Returns:
            Combined system prompt string.
        """
        context = self.load_bootstrap_context(agent_id)
        parts: list[str] = []

        if base_prompt:
            parts.append(base_prompt)

        # Add operating instructions
        if "operating_instructions" in context:
            parts.append(f"\n## Operating Instructions\n{context['operating_instructions']}")

        # Add persona
        if "persona" in context:
            parts.append(f"\n## Persona & Boundaries\n{context['persona']}")

        # Add tool notes
        if "tool_notes" in context:
            parts.append(f"\n## Tool Usage Notes\n{context['tool_notes']}")

        # Add user profile
        if "user_profile" in context:
            parts.append(f"\n## User Profile\n{context['user_profile']}")

        # Add first-run instructions (one-time)
        if "first_run" in context:
            parts.append(
                f"\n## First Run Instructions (ONE-TIME)\n"
                f"{context['first_run']}\n"
                f"NOTE: These instructions will not appear again."
            )

        return "\n".join(parts)

    def save_agent_file(
        self,
        agent_id: str,
        filename: str,
        content: str,
    ) -> None:
        """Write or update a bootstrap file for a specific agent.

        Args:
            agent_id: The agent ID.
            filename: File name (e.g. "AGENT.md", "PERSONA.md").
            content: File content.
        """
        agent_dir = self.workspace_dir / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        filepath = agent_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved {filename} for agent {agent_id}")

    def ensure_defaults(self) -> None:
        """Create default workspace template files if they don't exist."""
        defaults_dir = self.workspace_dir / "defaults"
        defaults_dir.mkdir(parents=True, exist_ok=True)

        defaults = {
            "AGENT.md": _DEFAULT_AGENT_MD,
            "PERSONA.md": _DEFAULT_PERSONA_MD,
            "TOOLS.md": _DEFAULT_TOOLS_MD,
        }

        for filename, content in defaults.items():
            filepath = defaults_dir / filename
            if not filepath.exists():
                filepath.write_text(content, encoding="utf-8")
                logger.info(f"Created default template: {filepath}")

    def _resolve_file(
        self,
        filename: str,
        agent_dir: Path,
        defaults_dir: Path,
    ) -> str | None:
        """Resolve a file through the three-tier hierarchy.

        Order: agent-specific → defaults → builtin fallback.

        Args:
            filename: The file to look for.
            agent_dir: Agent-specific directory.
            defaults_dir: Defaults directory.

        Returns:
            File content string, or None if not found at any tier.
        """
        # Tier 1: Agent-specific
        agent_file = agent_dir / filename
        if agent_file.exists():
            try:
                return agent_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read {agent_file}: {e}")

        # Tier 2: Defaults
        default_file = defaults_dir / filename
        if default_file.exists():
            try:
                return default_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read {default_file}: {e}")

        # Tier 3: Built-in fallback
        return _BUILTIN_FALLBACKS.get(filename)


# Singleton instance
_workspace_bootstrap: WorkspaceBootstrap | None = None


def get_workspace_bootstrap(workspace_dir: str | Path | None = None) -> WorkspaceBootstrap:
    """Get or create the workspace bootstrap singleton."""
    global _workspace_bootstrap
    if _workspace_bootstrap is None:
        _workspace_bootstrap = WorkspaceBootstrap(workspace_dir)
    return _workspace_bootstrap


# ---------------------------------------------------------------------------
# Default content templates
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_MD = """\
# Jarvis Agent - Operating Instructions

You are Jarvis, an autonomous AI copilot for your user.

## Core Responsibilities
- Proactively research, plan, and coordinate tasks
- Always explain your reasoning and cite sources
- Highlight when human approval is required (purchases, bookings, external actions)
- Provide concise, actionable responses

## Memory Protocol
- At the start of each session, review your memory for relevant context
- Before a session ends or context grows large, save important discoveries
  and decisions to your long-term memory
- When starting a multi-step task, note your plan in context so you can
  resume if interrupted

## Tool Usage
- Use tools when they add value (don't call tools unnecessarily)
- Always validate tool results before presenting them to the user
- If a tool call fails, explain what happened and try an alternative

## Communication Style
- Be proactive but not presumptuous
- Ask for clarification when the task is ambiguous
- Summarize complex findings into actionable recommendations
"""

_DEFAULT_PERSONA_MD = """\
# Persona & Boundaries

## Identity
- Name: Jarvis
- Role: Personal AI copilot and research assistant
- Tone: Professional, helpful, and concise

## Boundaries
- Never make purchases or bookings without explicit user approval
- Never share user data with third parties
- Never execute destructive operations without confirmation
- If uncertain about an action's consequences, ask before proceeding

## Style
- Use Markdown formatting when it improves readability
- Keep responses focused — avoid unnecessary preamble
- When presenting options, use numbered lists
- For research results, include source attribution
"""

_DEFAULT_TOOLS_MD = """\
# Tool Usage Notes

## Available Tools
- **web_search**: Use for current information, news, product research
- **read_url**: Use to extract content from specific URLs
- **execute_code**: Use for calculations, data processing, code generation
- **calculator**: Use for simple math expressions
- **get_time**: Use when current date/time is relevant

## Best Practices
- Prefer web_search over read_url for exploratory research
- Chain web_search → read_url for deep-dive on specific results
- Use execute_code for complex data transformations
- Use calculator for simple arithmetic (faster than execute_code)
"""

# Built-in fallbacks when no files exist at all
_BUILTIN_FALLBACKS: dict[str, str] = {
    "AGENT.md": (
        "You are Jarvis, an autonomous AI copilot that proactively researches, "
        "plans, and coordinates tasks for your user."
    ),
    "PERSONA.md": (
        "Be professional, helpful, and concise. Always explain your reasoning."
    ),
}
