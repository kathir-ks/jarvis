# Jarvis Agent Platform — High-Level Design

> **Version**: 0.5.0-beta | **Last Updated**: March 14, 2026

---

## 1. Vision & Purpose

Jarvis is a **multi-agent AI orchestration platform** where autonomous agents execute complex, multi-step tasks for individual users. Agents collaborate via peer-to-peer messaging, delegate work to sub-agents, maintain long-term memory, and use tools to interact with the external world.

**Key differentiators**:
- Multi-user agent ownership — each user has their own agents
- Dual-mode operation: full infrastructure (MongoDB/Redis/Qdrant) or zero-infrastructure (in-memory)
- Peer-to-peer agent communication with circuit breakers and health-aware load balancing
- DAG-based parallel task execution with dependency resolution
- Model Context Protocol (MCP) for tool discovery and sharing

---

## 2. System Architecture

### 2.1 Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    ENTRY POINTS                         │
│  run_platform.py   run_agent.py   run_multi_agent_demo  │
│  uvicorn main:app  (full API server)                    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    API LAYER (FastAPI)                   │
│  Core API (port 8000)     Platform API (port 9000)      │
│  /agents, /tasks, /mcp    /agents/register, /messages   │
│                           /directory, /heartbeat        │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                   SERVICE LAYER                         │
│  AgentService    TaskService    CommunicationPlatform   │
│  MessageService  MCPServer      PlatformService         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                   RUNTIME LAYER                         │
│  ┌─────────────────┐  ┌──────────────────────┐         │
│  │  AgentRunner     │  │  LiteAgentRunner     │         │
│  │  (full infra)    │  │  (zero infra)        │         │
│  └────────┬────────┘  └──────────┬───────────┘         │
│           │                      │                      │
│  ┌────────▼──────────────────────▼───────────┐         │
│  │ Shared Components:                         │         │
│  │  AgentCommunicationHub   AgentDirectory    │         │
│  │  DAGExecutor             CircuitBreaker    │         │
│  │  MasterAgentOrchestrator TaskAnalyzer      │         │
│  │  DelegationContextManager PromptBuilder    │         │
│  └───────────────────────────────────────────┘         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                 INTEGRATION LAYER                       │
│  LLMRouter → OpenAI | Gemini | Anthropic | OpenRouter   │
│  ToolRegistry → execute_code | web_search | read_url    │
│                  calculator | get_time                   │
│  MCPClient → remote tool discovery                      │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              DATA / INFRASTRUCTURE LAYER                 │
│                                                         │
│  Full Mode:              Lite Mode:                     │
│  ┌─────────┐ ┌───────┐  ┌──────────────────────────┐  │
│  │ MongoDB │ │ Redis │  │ InMemoryMessageBroker    │  │
│  │ (state) │ │(msgs) │  │ InMemoryAgentRepository  │  │
│  ├─────────┤ ├───────┤  │ (all in-process)         │  │
│  │ Qdrant  │ │Celery │  └──────────────────────────┘  │
│  │(vectors)│ │(tasks)│                                  │
│  └─────────┘ └───────┘                                  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Multi-User Platform Topology

```
         PRODUCTION (future — multi-process)

  ┌─────────────────────────────────────────┐
  │  Communication Platform (port 9000)     │
  │  MessageBroker + AgentDirectory         │
  │  REST API for register/send/broadcast   │
  └──────────────────┬──────────────────────┘
                     │ HTTP
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
┌───────────┐  ┌───────────┐  ┌───────────┐
│ kathir's  │  │ akilesh's │  │ aswin's   │
│ Runner    │  │ Runner    │  │ Runner    │
│ (proc 1)  │  │ (proc 2)  │  │ (proc 3)  │
└───────────┘  └───────────┘  └───────────┘

         DEMO (single process — current)

┌───────────────────────────────────────────┐
│  Shared InMemoryBroker + AgentDirectory   │
│  kathir's runner | akilesh's | aswin's    │
│  Zero network I/O — all in-process        │
└───────────────────────────────────────────┘
```

---

## 3. Core Entities

### 3.1 Agent
An autonomous AI entity with state, memory, tools, and an event loop.

| Field | Description |
|-------|-------------|
| `agent_id` | Unique identifier |
| `user_id` | Owning user |
| `agent_type` | MASTER or SUB_AGENT |
| `parent_agent_id` | Reference to master (null for masters) |
| `config` | LLM provider, model, temperature, max_tokens |
| `status` | IDLE → RUNNING → WAITING_APPROVAL → ERROR/TERMINATED |
| `short_term_memory` | Last 50 interactions (in-process) |
| `context` | Session state dictionary |
| `tools_available` | List of tool names agent can use |

### 3.2 Task
A unit of work with dependencies, priority, and retry logic.

| Field | Description |
|-------|-------------|
| `task_id` | Unique identifier |
| `agent_id` | Owning agent |
| `task_type` | RESEARCH, EXPLORATION, PURCHASE, BOOKING, CUSTOM |
| `status` | PENDING → RUNNING → COMPLETED/FAILED/CANCELLED |
| `depends_on` | List of prerequisite task IDs (DAG edges) |
| `priority` | 1-10 scale |
| `max_duration` | Timeout in seconds (default 300) |
| `max_retries` | Retry attempts (default 3) |

### 3.3 AgentMessage
Typed envelope for all inter-agent communication.

| Field | Description |
|-------|-------------|
| `message_id` | Auto-generated unique ID |
| `message_type` | PEER_MESSAGE, BROADCAST, REQUEST, RESPONSE, DELEGATION_*, HEARTBEAT |
| `sender_id` | Source agent |
| `recipient_id` | Target agent (empty for broadcasts) |
| `correlation_id` | Links request-response pairs |
| `content` | Payload dict |
| `ttl_seconds` | Time-to-live (0 = no expiry) |
| `priority` | LOW, NORMAL, HIGH, URGENT |

---

## 4. Component Descriptions

### 4.1 Agent Runner (Full)
The primary event loop for production use. Requires MongoDB, Redis, and Qdrant.

**Loop cycle** (every 1 second):
1. Poll Redis inbox → process messages → call LLM → execute tools
2. Handle delegation requests (sub-agents)
3. Poll pending tasks → build DAG → execute with concurrency limit
4. Checkpoint state to MongoDB every 30s
5. Send heartbeat every 15s

### 4.2 LiteAgentRunner (Zero-Infra)
Lightweight variant for demos and development. No external services needed.

**Features**:
- Constructor-injected broker, LLM provider, directory
- Interactive `chat()` for direct user conversation
- Auto-responds to incoming peer/broadcast messages via LLM
- Registers in AgentDirectory with user_id
- All memory in-process on Agent object

### 4.3 Communication Platform
Standalone service for multi-user agent messaging and discovery.

**Components**:
- `CommunicationPlatformService`: Wraps broker + directory
- REST API: 7 endpoints for register, send, broadcast, heartbeat, directory, health
- `InMemoryMessageBroker`: asyncio-based pub/sub with history
- Runs on port 9000

### 4.4 Agent Communication Hub
Per-agent hub for all messaging patterns.

- `send()` — peer-to-peer messaging
- `request()` — request-response with correlation and timeout
- `broadcast()` — all agents or topic-scoped
- `subscribe_topic()` — topic-based pub/sub
- `on_message()` — register type-specific handlers

### 4.5 Agent Directory
Health-aware agent registry with load balancing.

- Registration with user_id, capabilities, metadata
- Heartbeat processing with status tracking
- Find agent by capability (least-loaded, best success rate)
- Filter by user_id for multi-user isolation
- Stale agent eviction

### 4.6 Master Agent Orchestrator
Handles complex task delegation from master to sub-agents.

**Delegation workflow**:
1. Analyze task complexity (0-10 score)
2. If score >= 5: create delegation plan
3. Spawn/find sub-agents per capability
4. Build DelegationContext (parent memory, session state, prior results)
5. Delegate subtasks (sequential or parallel)
6. Collect results with timeout + circuit breaker
7. Aggregate with LLM synthesis
8. Store results in vector memory

### 4.7 Circuit Breaker
Per-agent failure protection preventing cascading failures.

- States: CLOSED → OPEN → HALF_OPEN → CLOSED
- Configurable failure threshold (default: 3)
- Recovery timeout (default: 60s)
- Exponential backoff retry utility
- Timeout enforcement wrapper

### 4.8 LLM Gateway
Unified interface for multiple LLM providers.

| Provider | Models | Status |
|----------|--------|--------|
| OpenAI | GPT-4, GPT-4o-mini | Complete |
| Gemini | Gemini 2.0 Flash, Gemma 3 4B | Complete (key rotation) |
| Anthropic | Claude models | Interface ready |
| OpenRouter | Any model via API | Complete |

### 4.9 Tool Registry
5 built-in tools with OpenAI function-calling schemas:

| Tool | Description |
|------|-------------|
| `execute_code` | Run Python in sandboxed environment |
| `web_search` | DuckDuckGo HTML search |
| `read_url` | Fetch and parse webpage content |
| `calculator` | Evaluate math expressions |
| `get_time` | Current date/time with timezone |

### 4.10 MCP Protocol
Model Context Protocol implementation for tool sharing.

- **MCPServer**: JSON-RPC 2.0 handler (initialize, tools/list, tools/call, ping)
- **MCPClient**: HTTP-based discovery with caching and fallback
- All 5 tools auto-exposed via MCP

### 4.11 Vector Memory Service
Three-collection semantic memory system (Qdrant).

- `user_interactions`: Conversation history with semantic search
- `content_discoveries`: Web content, products, articles
- `agent_knowledge`: Learned facts, patterns, preferences
- Automatic embedding generation (OpenAI text-embedding-3-small)

---

## 5. System Flows

### Flow 1: User Chat (Lite Mode)
```
User types message → LiteAgentRunner.chat()
  → PromptBuilder.build_agent_messages() (includes short-term memory)
  → LLMProvider.chat() (Gemini/OpenAI/etc.)
  → Response stored in agent.short_term_memory
  → Response returned to user
```

### Flow 2: Inter-Agent Message
```
Agent A sends message → AgentCommunicationHub.send()
  → broker.publish("agent:{B}:inbox", envelope)
  → B's comm hub callback fires
  → B builds prompt with "[Message from A]: ..."
  → B calls LLM → generates response
  → B sends response back via comm hub
```

### Flow 3: Task Delegation
```
Master receives complex task → TaskComplexityAnalyzer.analyze()
  → score >= 5 → MasterAgentOrchestrator.orchestrate_delegation()
  → Spawn sub-agents per capability
  → DelegationContextManager builds context
  → Delegate via broker with timeout + circuit breaker
  → Collect results → LLM synthesis → return
```

### Flow 4: DAG Task Execution
```
Agent polls pending tasks → DAGExecutor.execute()
  → Topological sort → identify ready tasks
  → Execute up to 5 in parallel
  → On completion: mark done, check dependents
  → On failure: cancel downstream tasks
```

---

## 6. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python 3.11+ | Async-native, AI ecosystem |
| Web Framework | FastAPI | Async API, auto-docs, Pydantic |
| Primary DB | MongoDB (Motor) | Agent state, tasks, metadata |
| Message Broker | Redis Streams / InMemoryBroker | Durable messaging |
| Vector DB | Qdrant | Semantic memory search |
| Task Queue | Celery + Redis | Background task execution |
| LLM Providers | OpenAI, Gemini, Anthropic, OpenRouter | Multi-provider routing |
| HTTP Client | httpx | Async HTTP for MCP |
| Containerization | Docker Compose | Service orchestration |
| Web Server | Uvicorn | ASGI server |

---

## 7. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python over Go | AI/LLM ecosystem dominance; I/O-bound workload |
| Framework | FastAPI | Async-native, Pydantic, auto-OpenAPI |
| DB | MongoDB | Schema-flexible for evolving agents |
| Message Broker | Redis Streams (+ in-memory fallback) | Durable with replay; in-memory for zero-infra demos |
| Vector DB | Qdrant | Self-hostable, Rust-fast, good filtering |
| Broker Abstraction | Protocol class | Enables Redis ↔ InMemory swap via DI |
| Agent Directory | In-process with user_id | Supports multi-user without external service |
| Circuit Breaker | Per-agent state | Isolates failures; one agent's errors don't affect others |
| Dual Runner | AgentRunner + LiteAgentRunner | Full features vs. zero-infra tradeoff |

---

## 8. Security Considerations

| Area | Current State | Priority |
|------|--------------|----------|
| Code Sandboxing | `execute_code` — restricted builtins only | HIGH (needs Docker isolation) |
| API Auth | Placeholder JWT | HIGH |
| Secrets | .env files | MEDIUM (needs vault) |
| Cross-user Privacy | user_id filtering in directory | LOW (enforcement needed) |
| Transport | No TLS in dev | MEDIUM (Traefik for prod) |

---

## 9. Scalability Path

| Phase | Topology | Scale |
|-------|----------|-------|
| Current | Single process, in-memory | 1-10 agents, demo |
| Next | Platform service + agent processes | 10-50 agents |
| Future | Kubernetes, managed DBs | 100+ agents, multi-tenant |

---

**Related Documents**:
- [CLAUDE.md](CLAUDE.md) — System overview with component details
- [LLD.md](LLD.md) — Low-level design with implementation specifics
- [CURRENT_STATE.md](CURRENT_STATE.md) — Module-by-module status assessment
- [PLATFORM_API.md](PLATFORM_API.md) — Communication Platform API reference
- [LLM_INTEGRATION.md](LLM_INTEGRATION.md) — LLM provider guide
- [MCP_SETUP.md](MCP_SETUP.md) — MCP protocol setup
