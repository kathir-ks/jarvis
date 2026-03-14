# Jarvis Agent Platform

Multi-agent AI orchestration platform with multi-user support, inter-agent communication, and infrastructure-free operation mode.

## Quick Start

### Zero-Infrastructure Demo (Recommended)

No Docker, MongoDB, Redis, or Qdrant required. Just Python and an LLM API key.

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set your API key
export GEMINI_API_KEY="your-key-here"

# Run the multi-user demo (3 agents for kathir, akilesh, aswin)
python run_multi_agent_demo.py --provider gemini --model gemma-3-4b-it

# Or start a single agent REPL
python run_agent.py --user kathir --provider gemini --model gemma-3-4b-it

# Or start the Communication Platform (port 9000)
python run_platform.py
```

### Full Infrastructure (Docker Compose)

For production features (persistent state, vector memory, durable messaging):

```bash
cd docker
cp .env.example .env
docker-compose up -d

# Run API server
uvicorn jarvis.app.main:app --reload

# Run Celery worker (separate terminal)
celery -A jarvis.app.tasks.celery_app worker --loglevel=info
```

## Project Structure

```
jarvis/app/
  runtime/           # Agent event loops, directory, communication, circuit breaker
  llm/               # LLM providers (OpenAI, Gemini, Anthropic, OpenRouter), tools
  lite/              # Zero-infrastructure implementations (in-memory broker & repo)
  platform/          # Communication Platform service + REST API
  mcp/               # Model Context Protocol (server, client, protocol)
  db/                # MongoDB, Redis, Qdrant clients & repositories
  messaging/         # Message broker interface + Redis Streams implementation
  api/routes/        # FastAPI routers (agents, tasks, MCP)
  services/          # Business logic facades
  core/              # Settings, logging

# Entry points
run_platform.py          # Communication Platform service (port 9000)
run_agent.py             # Single agent REPL
run_multi_agent_demo.py  # Multi-user demo (3 agents, zero infra)
run_gemma_agents.py      # Standalone Gemma agent demo
```

## API Endpoints

### Core Agent API (port 8000)
- `GET /health` — Health check
- `POST /agents` — Create agent
- `GET /agents/{agent_id}` — Get agent state
- `POST /agents/{agent_id}/messages` — Send message to agent
- `POST /agents/{agent_id}/start` — Start agent event loop
- `POST /agents/{agent_id}/tasks` — Submit task
- `GET /tasks/{task_id}` — Get task status

### Communication Platform API (port 9000)
- `POST /api/v1/agents/register` — Register agent with user + capabilities
- `POST /api/v1/agents/unregister` — Remove agent
- `POST /api/v1/messages/send` — Route message between agents
- `POST /api/v1/messages/broadcast` — Broadcast to all agents
- `POST /api/v1/heartbeat` — Agent health heartbeat
- `GET  /api/v1/directory/agents` — List agents (filter by user_id)
- `GET  /api/v1/health` — Platform health

See [PLATFORM_API.md](PLATFORM_API.md) for full API reference.

## Documentation

- [CLAUDE.md](CLAUDE.md) — **System Overview** (architecture, components, flows)
- [CURRENT_STATE.md](CURRENT_STATE.md) — **Current State Assessment** (module-by-module status)
- [PLATFORM_API.md](PLATFORM_API.md) — **Communication Platform API Reference**
- [LLM_INTEGRATION.md](LLM_INTEGRATION.md) — LLM Provider Guide
- [MCP_SETUP.md](MCP_SETUP.md) — MCP Protocol Setup
- [IMPLEMENTATION.md](IMPLEMENTATION.md) — Implementation Progress

## Environment Variables

Key variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | For Gemini/Gemma models |
| `OPENAI_API_KEY` | OpenAI API key | For GPT models |
| `OPENROUTER_API_KEY` | OpenRouter API key | For OpenRouter models |
| `ANTHROPIC_API_KEY` | Anthropic API key | For Claude models |

See `docker/.env.example` for full configuration options.

## Development Status

**Phase 5 Complete (98%)** — Multi-user Communication Platform with zero-infrastructure agent runners.

✅ Completed:
- Agent runtime with event loop, checkpointing, and tool calling
- LLM providers: OpenAI, Gemini (with key rotation), Anthropic, OpenRouter
- 5 tools: execute_code, calculator, get_time, web_search, read_url
- MCP protocol (server, client, tool discovery)
- Vector memory with Qdrant for long-term context
- DAG executor for parallel task execution
- Master-SubAgent delegation with context propagation
- Agent communication: peer-to-peer, broadcast, topic pub/sub
- Agent directory with health tracking and load balancing
- Circuit breaker with exponential backoff
- **Multi-user Communication Platform (Phase 5)**
- **LiteAgentRunner — zero-infrastructure agent operation**
- **InMemoryBroker + InMemoryRepo — no external services needed**
- 172+ unit tests

⏳ Remaining:
- HttpPlatformBroker (multi-process agent deployment)
- Security hardening (sandboxing, authentication)
- Observability (Prometheus, OpenTelemetry)

## License

Proprietary
