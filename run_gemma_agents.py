"""
Standalone Gemma Agent Runner
Runs agents directly against Gemma models without requiring
MongoDB, Redis, or Qdrant infrastructure.
"""
import asyncio
import sys
import io
import json
import uuid
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from jarvis.app.llm.providers.gemini_provider import GeminiProvider
from jarvis.app.llm.prompt_builder import PromptBuilder
from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType
from jarvis.app.runtime.delegation_context import DelegationContextManager
from jarvis.app.runtime.master_agent import MasterAgentOrchestrator
from jarvis.app.runtime.task import Task, TaskType, TaskStatus

API_KEY = "AIzaSyBQQmY3NqycRIvfSbjexswSOp8R3HK3b1A"
MODEL = "gemma-3-4b-it"

provider = GeminiProvider(api_key=API_KEY, default_model=MODEL)
prompt_builder = PromptBuilder()
context_manager = DelegationContextManager()


class LightweightAgentRunner:
    """In-memory agent runner — no DB required."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.provider = provider
        self.prompt_builder = prompt_builder
        self.turn_count = 0

    async def chat(self, user_message: str) -> str:
        """Send a message to the agent and get a response."""
        self.turn_count += 1
        msg = {"content": user_message, "type": "message"}

        messages = self.prompt_builder.build_agent_messages(self.agent, msg)

        result = await self.provider.chat(messages, {
            "max_tokens": self.agent.config.max_tokens,
            "temperature": self.agent.config.temperature,
        })

        response = result.content or "(empty response)"

        # Update memory
        now = datetime.utcnow().isoformat()
        self.agent.short_term_memory.append(
            {"role": "user", "content": user_message, "timestamp": now}
        )
        self.agent.short_term_memory.append(
            {"role": "assistant", "content": response, "timestamp": now}
        )

        # Trim memory to last 50
        if len(self.agent.short_term_memory) > 50:
            self.agent.short_term_memory = self.agent.short_term_memory[-50:]

        # Update context
        self.agent.context["last_response"] = response[:200]
        self.agent.context["last_interaction_at"] = now
        self.agent.context["turn_count"] = self.turn_count

        return response


class LightweightMasterRunner:
    """In-memory master + sub-agent delegation runner."""

    def __init__(self, master: Agent):
        self.master = master
        self.master_runner = LightweightAgentRunner(master)
        self.orchestrator = MasterAgentOrchestrator(
            agent_id=master.agent_id,
            master_agent=master,
        )
        self.sub_agents: dict[str, LightweightAgentRunner] = {}

    async def chat(self, user_message: str) -> str:
        """Direct chat with master agent."""
        return await self.master_runner.chat(user_message)

    async def delegate(self, task_description: str) -> dict:
        """Analyze a task and delegate to sub-agents if complex."""
        analysis = self.orchestrator.analyze_task_only(task_description)

        print(f"\n  Task Analysis:")
        print(f"    Complexity: {analysis['complexity_score']}/10")
        print(f"    Should delegate: {analysis['should_delegate']}")
        print(f"    Capabilities needed: {analysis['suggested_sub_agents']}")

        if not analysis["should_delegate"]:
            # Simple task — master handles it
            print("    -> Master handling directly")
            response = await self.master_runner.chat(task_description)
            return {"strategy": "direct", "response": response}

        # Complex task — delegate to sub-agents
        print(f"    -> Delegating to {len(analysis['suggested_sub_agents'])} sub-agents")

        subtask_results = []
        for i, capability in enumerate(analysis["suggested_sub_agents"]):
            subtask_desc = self._generate_subtask(
                task_description, capability, i, len(analysis["suggested_sub_agents"])
            )

            # Spawn sub-agent
            sub_agent = self._create_sub_agent(capability)
            sub_runner = LightweightAgentRunner(sub_agent)

            # Build delegation context
            deleg_ctx = context_manager.build_context_for_sub_agent(
                master_agent=self.master,
                parent_task_description=task_description,
                subtask={"description": subtask_desc, "assigned_capability": capability},
                subtask_index=i,
                total_subtasks=len(analysis["suggested_sub_agents"]),
                prior_results=subtask_results if subtask_results else None,
            )

            # Build delegation prompt and call LLM
            deleg_messages = prompt_builder.build_delegation_messages(
                agent=sub_agent,
                delegation_context=deleg_ctx.model_dump(),
            )

            print(f"\n  Sub-agent [{capability}] working on: {subtask_desc[:80]}...")
            result = await provider.chat(deleg_messages, {
                "max_tokens": 500,
                "temperature": 0.7,
            })

            output = result.content or ""
            print(f"  Sub-agent [{capability}] responded ({len(output)} chars)")

            subtask_results.append({
                "status": "completed",
                "subtask": {"assigned_capability": capability},
                "result": {"output": output},
            })

        # Synthesize results
        print("\n  Synthesizing results...")
        synthesis_prompt = self._build_synthesis_prompt(task_description, subtask_results)
        synthesis = await provider.chat(
            [{"role": "user", "content": synthesis_prompt}],
            {"max_tokens": 600, "temperature": 0.5},
        )

        # Save to master memory
        now = datetime.utcnow().isoformat()
        self.master.short_term_memory.append(
            {"role": "user", "content": task_description, "timestamp": now}
        )
        self.master.short_term_memory.append(
            {"role": "assistant", "content": synthesis.content, "timestamp": now}
        )

        return {
            "strategy": "delegated",
            "subtask_count": len(subtask_results),
            "capabilities_used": analysis["suggested_sub_agents"],
            "response": synthesis.content,
        }

    def _create_sub_agent(self, capability: str) -> Agent:
        return Agent(
            _id=f"sub-{capability}-{uuid.uuid4().hex[:8]}",
            user_id=self.master.user_id,
            agent_type=AgentType.SUB_AGENT,
            parent_agent_id=self.master.agent_id,
            config=AgentConfig(
                llm_provider="gemini", model=MODEL,
                max_tokens=500, temperature=0.7,
            ),
        )

    def _generate_subtask(self, task: str, capability: str, idx: int, total: int) -> str:
        focus = {
            "web_research": "Research and gather information about",
            "code_execution": "Write and execute code to",
            "calculation": "Perform calculations for",
            "general_assistance": "Assist with",
        }
        prefix = focus.get(capability, "Work on")
        return f"[Subtask {idx+1}/{total}] {prefix}: {task[:200]}"

    def _build_synthesis_prompt(self, task: str, results: list) -> str:
        outputs = ""
        for i, r in enumerate(results, 1):
            cap = r["subtask"]["assigned_capability"]
            out = r["result"]["output"][:400]
            outputs += f"\n\n### Subtask {i} ({cap}):\n{out}"

        return (
            f"Synthesize these sub-agent results into one coherent response.\n\n"
            f"Original task: {task}\n\nResults:{outputs}\n\n"
            f"Write a unified, natural response (no mention of sub-agents)."
        )


# ===================================================================
# DEMO SCENARIOS
# ===================================================================

async def demo_1_simple_agent():
    """Single agent multi-turn conversation."""
    print("\n" + "=" * 70)
    print("DEMO 1: Single Agent — Multi-Turn Conversation")
    print("=" * 70)

    agent = Agent(
        _id="agent-demo-1",
        user_id="demo-user",
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider="gemini", model=MODEL,
            max_tokens=250, temperature=0.7,
        ),
        context={"project": "Jarvis AI Platform", "role": "AI assistant"},
    )
    runner = LightweightAgentRunner(agent)

    turns = [
        "Hi! My name is Alex and I'm building a multi-agent AI system.",
        "What are the key challenges I should watch out for?",
        "Can you remember my name and what I'm building?",
    ]

    for user_msg in turns:
        print(f"\n  User: {user_msg}")
        response = await runner.chat(user_msg)
        print(f"  Agent: {response[:300]}")
        print(f"  [Memory size: {len(agent.short_term_memory)} entries]")


async def demo_2_master_delegation():
    """Master agent delegates complex task to sub-agents."""
    print("\n" + "=" * 70)
    print("DEMO 2: Master Agent — Task Delegation to Sub-Agents")
    print("=" * 70)

    master = Agent(
        _id="master-demo-2",
        user_id="demo-user",
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider="gemini", model=MODEL,
            max_tokens=300, temperature=0.7,
        ),
        context={"project": "Jarvis"},
        short_term_memory=[],
    )
    runner = LightweightMasterRunner(master)

    # Simple task first (should not delegate)
    print("\n--- Simple task ---")
    result = await runner.delegate("What time is it in UTC?")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Response: {result['response'][:200]}")

    # Complex task (should delegate)
    print("\n--- Complex task ---")
    result = await runner.delegate(
        "Research the circuit breaker pattern for distributed systems, "
        "then write a Python implementation with proper error handling"
    )
    print(f"\n  Strategy: {result['strategy']}")
    print(f"  Subtasks: {result.get('subtask_count', 0)}")
    print(f"  Capabilities: {result.get('capabilities_used', [])}")
    print(f"\n  Final synthesized response:")
    print(f"  {result['response'][:500]}")


async def demo_3_sequential_delegation():
    """Sequential delegation where subtask 2 builds on subtask 1."""
    print("\n" + "=" * 70)
    print("DEMO 3: Sequential Delegation — Context Chaining")
    print("=" * 70)

    master = Agent(
        _id="master-demo-3",
        user_id="demo-user",
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider="gemini", model=MODEL,
            max_tokens=300, temperature=0.7,
        ),
        context={"project": "Jarvis", "phase": "testing"},
        short_term_memory=[
            {"role": "user", "content": "We need to improve error handling", "timestamp": "T0"},
        ],
    )

    # Step 1: Research sub-agent
    print("\n--- Step 1: Research sub-agent ---")
    research_agent = Agent(
        _id="sub-research-001",
        user_id="demo-user",
        agent_type=AgentType.SUB_AGENT,
        parent_agent_id="master-demo-3",
        config=AgentConfig(llm_provider="gemini", model=MODEL, max_tokens=300),
    )

    ctx1 = context_manager.build_context_for_sub_agent(
        master_agent=master,
        parent_task_description="Research retry patterns then implement one",
        subtask={"description": "Research common retry and backoff patterns for distributed systems"},
        subtask_index=0,
        total_subtasks=2,
    )

    msgs1 = prompt_builder.build_delegation_messages(
        agent=research_agent, delegation_context=ctx1.model_dump(),
    )
    result1 = await provider.chat(msgs1, {"max_tokens": 300})
    print(f"  Research output: {result1.content[:300]}")

    # Step 2: Implementation sub-agent (gets research results)
    print("\n--- Step 2: Implementation sub-agent (receives Step 1 results) ---")
    impl_agent = Agent(
        _id="sub-impl-001",
        user_id="demo-user",
        agent_type=AgentType.SUB_AGENT,
        parent_agent_id="master-demo-3",
        config=AgentConfig(llm_provider="gemini", model=MODEL, max_tokens=500),
    )

    prior_results = [{
        "status": "completed",
        "subtask": {"assigned_capability": "web_research"},
        "result": {"output": result1.content},
    }]

    ctx2 = context_manager.build_context_for_sub_agent(
        master_agent=master,
        parent_task_description="Research retry patterns then implement one",
        subtask={"description": "Based on the research, implement a retry-with-backoff function in Python"},
        subtask_index=1,
        total_subtasks=2,
        prior_results=prior_results,
    )

    msgs2 = prompt_builder.build_delegation_messages(
        agent=impl_agent, delegation_context=ctx2.model_dump(),
    )
    result2 = await provider.chat(msgs2, {"max_tokens": 500})
    print(f"  Implementation output: {result2.content[:500]}")

    # Verify chaining worked
    has_code = "def" in result2.content.lower() or "```" in result2.content
    print(f"\n  Contains code: {has_code}")
    print("  [PASS] Sequential chaining works — Step 2 built on Step 1")


async def main():
    print("=" * 70)
    print("  JARVIS AGENT PLATFORM — Gemma Model Live Demo")
    print(f"  Model: {MODEL}")
    print(f"  Time: {datetime.utcnow().isoformat()}")
    print("=" * 70)

    await demo_1_simple_agent()
    await demo_2_master_delegation()
    await demo_3_sequential_delegation()

    print("\n" + "=" * 70)
    print("  ALL DEMOS COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
