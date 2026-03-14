"""Start a single LiteAgentRunner that connects to the Communication Platform.

Usage:
    python run_agent.py --user kathir --model gemma-3-4b-it
    python run_agent.py --user akilesh --model gemma-3-4b-it --provider gemini

For now, this runs in standalone mode with an in-memory broker (no HTTP
platform connection).  The ``--platform`` flag is accepted but reserved for
when ``HttpPlatformBroker`` is implemented.
"""
import argparse
import asyncio
import io
import sys
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from jarvis.app.lite.memory_broker import InMemoryMessageBroker
from jarvis.app.llm.prompt_builder import PromptBuilder
from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType
from jarvis.app.runtime.agent_directory import AgentDirectory
from jarvis.app.runtime.lite_agent_runner import LiteAgentRunner


def _build_provider(provider_name: str, model: str):
    """Construct an LLM provider from name + model."""
    if provider_name == "gemini":
        import os
        from jarvis.app.llm.providers.gemini_provider import GeminiProvider
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("WARNING: GEMINI_API_KEY not set — LLM calls will fail")
        return GeminiProvider(api_key=api_key, default_model=model)

    if provider_name == "openrouter":
        import os
        from jarvis.app.llm.providers.openrouter_provider import OpenRouterProvider
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            print("WARNING: OPENROUTER_API_KEY not set — LLM calls will fail")
        return OpenRouterProvider(api_key=api_key, default_model=model)

    if provider_name == "openai":
        import os
        from jarvis.app.llm.providers.openai_provider import OpenAIProvider
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("WARNING: OPENAI_API_KEY not set — LLM calls will fail")
        return OpenAIProvider(api_key=api_key, default_model=model)

    raise ValueError(f"Unknown provider: {provider_name}")


async def interactive_loop(runner: LiteAgentRunner, user: str) -> None:
    """Simple REPL for chatting with the agent."""
    print(f"\nAgent ready for user '{user}'. Type 'quit' to exit.\n")
    while True:
        try:
            user_input = input(f"[{user}] > ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() in ("quit", "exit", "q"):
            break
        if not user_input.strip():
            continue

        response = await runner.chat(user_input)
        print(f"Agent: {response}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single Jarvis agent")
    parser.add_argument("--user", required=True, help="User ID (e.g. kathir)")
    parser.add_argument("--model", default="gemma-3-4b-it", help="LLM model name")
    parser.add_argument("--provider", default="gemini", help="LLM provider (gemini, openrouter, openai)")
    parser.add_argument("--platform", default=None, help="Platform URL (reserved for future HTTP broker)")
    args = parser.parse_args()

    agent_id = f"agent-{args.user}-{uuid.uuid4().hex[:6]}"

    broker = InMemoryMessageBroker()
    directory = AgentDirectory()
    llm_provider = _build_provider(args.provider, args.model)
    prompt_builder = PromptBuilder()

    agent = Agent(
        _id=agent_id,
        user_id=args.user,
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider=args.provider,
            model=args.model,
            max_tokens=1024,
            temperature=0.7,
        ),
        context={"project": "Jarvis AI Platform"},
    )

    runner = LiteAgentRunner(
        agent=agent,
        broker=broker,
        llm_provider=llm_provider,
        directory=directory,
        prompt_builder=prompt_builder,
    )

    asyncio.run(interactive_loop(runner, args.user))


if __name__ == "__main__":
    main()
