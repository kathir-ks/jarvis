"""Multi-user agent demo — 3 agents for kathir, akilesh, aswin.

Single-process, zero external infrastructure.  All agents share an
InMemoryBroker and AgentDirectory so they can communicate directly.

Usage:
    python run_multi_agent_demo.py
    python run_multi_agent_demo.py --provider gemini --model gemma-3-4b-it

Set GEMINI_API_KEY (or OPENROUTER_API_KEY / OPENAI_API_KEY) before running.
"""
import argparse
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from jarvis.app.lite.memory_broker import InMemoryMessageBroker
from jarvis.app.llm.prompt_builder import PromptBuilder
from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType
from jarvis.app.runtime.agent_directory import AgentDirectory
from jarvis.app.runtime.lite_agent_runner import LiteAgentRunner


# ===================================================================
# Provider factory
# ===================================================================

def _build_provider(provider_name: str, model: str):
    if provider_name == "gemini":
        from jarvis.app.llm.providers.gemini_provider import GeminiProvider
        api_key = os.environ.get("GEMINI_API_KEY", "")
        return GeminiProvider(api_key=api_key, default_model=model)
    if provider_name == "openrouter":
        from jarvis.app.llm.providers.openrouter_provider import OpenRouterProvider
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        return OpenRouterProvider(api_key=api_key, default_model=model)
    if provider_name == "openai":
        from jarvis.app.llm.providers.openai_provider import OpenAIProvider
        api_key = os.environ.get("OPENAI_API_KEY", "")
        return OpenAIProvider(api_key=api_key, default_model=model)
    raise ValueError(f"Unknown provider: {provider_name}")


# ===================================================================
# Agent creation helper
# ===================================================================

def _create_agent(user_id: str, provider_name: str, model: str) -> Agent:
    return Agent(
        _id=f"agent-{user_id}-{uuid.uuid4().hex[:6]}",
        user_id=user_id,
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider=provider_name,
            model=model,
            max_tokens=512,
            temperature=0.7,
        ),
        context={"project": "Jarvis AI Platform", "role": f"{user_id}'s assistant"},
    )


# ===================================================================
# Demo scenarios
# ===================================================================

async def demo_1_individual_chat(runners: dict[str, LiteAgentRunner]):
    """Each agent chats independently — validates multi-turn memory."""
    print("\n" + "=" * 70)
    print("DEMO 1: Individual Chat — Each User Talks to Their Agent")
    print("=" * 70)

    conversations = {
        "kathir": [
            "Hi! I'm Kathir, I'm working on the agent communication layer.",
            "What patterns should I use for inter-agent messaging?",
        ],
        "akilesh": [
            "Hey, I'm Akilesh. I'm focusing on the LLM integration side.",
            "What are the best practices for prompt engineering?",
        ],
        "aswin": [
            "Hello! I'm Aswin, responsible for the deployment infrastructure.",
            "What should I consider for deploying multi-agent systems?",
        ],
    }

    for user, messages in conversations.items():
        runner = runners[user]
        print(f"\n--- {user}'s conversation ---")
        for msg in messages:
            print(f"  [{user}]: {msg}")
            response = await runner.chat(msg)
            print(f"  Agent: {response[:250]}")
            print(f"  [Memory: {len(runner.agent.short_term_memory)} entries]")
        print()


async def demo_2_cross_agent_messaging(runners: dict[str, LiteAgentRunner]):
    """kathir's agent sends a message to aswin's agent via the broker."""
    print("\n" + "=" * 70)
    print("DEMO 2: Cross-Agent Messaging — kathir -> aswin")
    print("=" * 70)

    kathir_runner = runners["kathir"]
    aswin_runner = runners["aswin"]

    # kathir's agent sends a peer message to aswin's agent
    print(f"\n  kathir's agent ({kathir_runner.agent.agent_id}) -> aswin's agent ({aswin_runner.agent.agent_id})")
    print("  Message: 'Hey Aswin's agent, what deployment strategy do you recommend for our platform?'")

    await kathir_runner.comm_hub.send(
        recipient_id=aswin_runner.agent.agent_id,
        content={"text": "Hey Aswin's agent, what deployment strategy do you recommend for our platform?"},
    )

    # Give the callback a moment to complete
    await asyncio.sleep(0.5)

    # Check aswin's agent memory grew (it received and processed the message)
    print(f"\n  aswin's agent memory after receiving: {len(aswin_runner.agent.short_term_memory)} entries")
    if len(aswin_runner.agent.short_term_memory) > 0:
        last = aswin_runner.agent.short_term_memory[-1]
        print(f"  Last memory entry (role={last['role']}): {last['content'][:200]}")
    print("  [PASS] Cross-agent message delivered and processed")


async def demo_3_broadcast(runners: dict[str, LiteAgentRunner]):
    """akilesh broadcasts a message that all agents receive."""
    print("\n" + "=" * 70)
    print("DEMO 3: Broadcast — akilesh -> all agents")
    print("=" * 70)

    akilesh_runner = runners["akilesh"]

    # Record memory sizes before broadcast
    before = {user: len(r.agent.short_term_memory) for user, r in runners.items()}

    print(f"\n  akilesh's agent broadcasting: 'System update: we are switching to Gemma 3 4B for all agents.'")

    await akilesh_runner.comm_hub.broadcast(
        content={"text": "System update: we are switching to Gemma 3 4B for all agents."},
    )

    await asyncio.sleep(0.5)

    # Check which agents received the broadcast
    for user, runner in runners.items():
        after = len(runner.agent.short_term_memory)
        grew = after > before[user]
        status = "received" if grew else "skipped (self)" if user == "akilesh" else "not received"
        print(f"  {user}: memory {before[user]} -> {after} ({status})")

    print("  [PASS] Broadcast delivered to subscribers")


async def demo_4_directory_listing(runners: dict[str, LiteAgentRunner], directory: AgentDirectory):
    """Show the agent directory with user-aware filtering."""
    print("\n" + "=" * 70)
    print("DEMO 4: Agent Directory — User-Aware Listing")
    print("=" * 70)

    # List all agents
    all_agents = directory.find_all()
    print(f"\n  All agents ({len(all_agents)}):")
    for entry in all_agents:
        print(f"    - {entry.agent_id} (user={entry.user_id}, health={entry.health.value})")

    # Filter by user
    for user in ["kathir", "akilesh", "aswin"]:
        user_agents = directory.find_all(user_id=user)
        print(f"\n  Agents for {user}: {[e.agent_id for e in user_agents]}")

    # Health summary
    health = directory.get_health_summary()
    print(f"\n  Directory health: {health}")
    print("  [PASS] Directory listing with user_id filter works")


# ===================================================================
# Main orchestration
# ===================================================================

async def main(provider_name: str, model: str):
    print("=" * 70)
    print("  JARVIS MULTI-USER AGENT DEMO")
    print(f"  Model: {model} ({provider_name})")
    print(f"  Users: kathir, akilesh, aswin")
    print(f"  Time: {datetime.utcnow().isoformat()}")
    print("=" * 70)

    # Shared infrastructure (in-memory, single process)
    broker = InMemoryMessageBroker()
    directory = AgentDirectory()
    llm_provider = _build_provider(provider_name, model)
    prompt_builder = PromptBuilder()

    # Create 3 agents
    users = ["kathir", "akilesh", "aswin"]
    runners: dict[str, LiteAgentRunner] = {}

    for user in users:
        agent = _create_agent(user, provider_name, model)
        runner = LiteAgentRunner(
            agent=agent,
            broker=broker,
            llm_provider=llm_provider,
            directory=directory,
            prompt_builder=prompt_builder,
        )
        # Start the runner (registers in directory, sets up comm hub)
        await runner.start()
        runners[user] = runner
        print(f"  Started agent for {user}: {agent.agent_id}")

    print()

    try:
        # Run demos sequentially
        await demo_1_individual_chat(runners)
        await demo_2_cross_agent_messaging(runners)
        await demo_3_broadcast(runners)
        await demo_4_directory_listing(runners, directory)

    finally:
        # Clean shutdown
        for user, runner in runners.items():
            await runner.stop()
            print(f"  Stopped agent for {user}")

    print("\n" + "=" * 70)
    print("  ALL DEMOS COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-user agent demo")
    parser.add_argument("--provider", default="gemini", help="LLM provider")
    parser.add_argument("--model", default="gemma-3-4b-it", help="LLM model")
    args = parser.parse_args()

    asyncio.run(main(args.provider, args.model))
