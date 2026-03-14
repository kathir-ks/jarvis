# Jarvis Agent Platform — Low-Level Design

> **Version**: 0.5.0-beta | **Last Updated**: March 14, 2026

---

## 1. Scope

This document covers the implementation-level design of the Jarvis platform, including data models, class hierarchies, API specifications, runtime architecture, and deployment topology.

---

## 2. Runtime Topology

### 2.1 Full Infrastructure (Docker Compose)

```
Services:
  api-gateway     (FastAPI + Uvicorn, port 8000)
  agent-runtime   (AgentRunner event loops)
  task-executor   (Celery worker pool)
  mongodb         (7.0 — primary datastore)
  redis           (7.2 — streams, cache, Celery broker)
  qdrant          (1.7.4 — vector memory)
```

### 2.2 Lite Mode (Zero Infrastructure)

```
Single Python process:
  InMemoryMessageBroker   (asyncio pub/sub)
  InMemoryAgentRepository (dict-backed)
  LiteAgentRunner × N     (one per user/agent)
  AgentDirectory           (shared, user-aware)
```

### 2.3 Platform Mode (Standalone Service)

```
Communication Platform    (FastAPI, port 9000)
  InMemoryMessageBroker
  AgentDirectory
  REST API (7 endpoints)
```

---

## 3. Project Structure

```
jarvis/app/
├── runtime/
│   ├── agent.py                # Agent, AgentConfig, AgentType, AgentStatus
│   ├── task.py                 # Task, TaskType, TaskStatus
│   ├── agent_runner.py         # Full event loop (MongoDB/Redis/Qdrant)
│   ├── lite_agent_runner.py    # Lightweight event loop (zero infra)
│   ├── dag_executor.py         # DAG topological sort + parallel execution
│   ├── agent_directory.py      # Health-aware registry with user_id
│   ├── agent_communication.py  # AgentCommunicationHub, AgentMessage
│   ├── agent_capabilities.py   # AgentCapability registry
│   ├── circuit_breaker.py      # CircuitBreaker with backoff
│   ├── master_agent.py         # MasterAgentOrchestrator
│   ├── delegation_context.py   # DelegationContext propagation
│   ├── task_analyzer.py        # TaskComplexityAnalyzer
│   └── workspace_bootstrap.py  # Agent persona/identity from markdown
│
├── llm/
│   ├── base.py                 # LLMResult, LLMProvider protocol
│   ├── router.py               # LLMRouter (multi-provider)
│   ├── prompt_builder.py       # PromptBuilder (token-aware)
│   ├── embeddings.py           # OpenAI text-embedding-3-small
│   ├── tool_registry.py        # ToolRegistry with OpenAI/MCP schemas
│   ├── providers/
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py  # With key rotation
│   │   ├── anthropic_provider.py
│   │   └── openrouter_provider.py
│   └── tools/
│       ├── core_tools.py       # execute_code, calculator, get_time
│       ├── web_tools.py        # web_search, read_url
│       └── init_tools.py       # Auto-registration at startup
│
├── lite/                       # Zero-infrastructure implementations
│   ├── memory_broker.py        # InMemoryMessageBroker
│   └── memory_repo.py          # InMemoryAgentRepository
│
├── platform/                   # Communication Platform service
│   ├── app.py                  # create_platform_app() factory
│   ├── api.py                  # FastAPI router (7 endpoints)
│   ├── service.py              # CommunicationPlatformService
│   └── models.py               # Pydantic request/response models
│
├── mcp/
│   ├── server.py               # MCP JSON-RPC 2.0 server
│   ├── client.py               # MCP HTTP client with caching
│   └── protocol.py             # MCP protocol definitions
│
├── db/
│   ├── repositories.py         # AgentRepository, TaskRepository
│   ├── vector_memory.py        # VectorMemoryService (Qdrant)
│   ├── mongo_client.py         # Motor async MongoDB client
│   └── redis_client.py         # Async Redis client
│
├── messaging/
│   ├── broker.py               # MessageBroker (Redis Streams)
│   └── broker_interface.py     # MessageBrokerProtocol
│
├── api/routes/
│   ├── agents.py               # Agent CRUD + lifecycle
│   ├── tasks.py                # Task management
│   └── mcp.py                  # MCP JSON-RPC endpoint
│
├── services/
│   ├── agents.py               # AgentService facade
│   ├── tasks.py                # TaskService facade
│   └── messages.py             # MessageService
│
├── core/
│   ├── settings.py             # Pydantic Settings (env-based)
│   ├── app.py                  # FastAPI app factory
│   └── logging.py              # Structured logging
│
└── main.py                     # ASGI entry point
```

---

## 4. Core Data Models

### 4.1 Agent (Pydantic)

```python
class Agent(BaseModel):
    agent_id: str               # Field(alias="_id")
    user_id: str
    agent_type: AgentType       # MASTER | SUB_AGENT
    parent_agent_id: str | None
    config: AgentConfig         # llm_provider, model, temperature, max_tokens,
                                # loop_interval_seconds, checkpoint_interval_seconds,
                                # mcp_server_url, mcp_timeout_seconds
    tools_available: list[str]
    status: AgentStatus         # IDLE | RUNNING | WAITING_APPROVAL | ERROR | TERMINATED
    context: dict[str, Any]     # Session state
    short_term_memory: list[dict[str, Any]]  # Last 50 interactions
    task_queue_meta: dict[str, Any]
    last_checkpoint: datetime | None
    created_at: datetime
    updated_at: datetime
```

### 4.2 Task (Pydantic)

```python
class Task(BaseModel):
    task_id: str
    agent_id: str
    parent_task_id: str | None
    task_type: TaskType         # RESEARCH | EXPLORATION | PURCHASE | BOOKING | CUSTOM
    task_description: str
    task_params: dict[str, Any]
    priority: int               # 1-10
    llm_config: dict | None
    tools: list[str]
    max_duration: int = 300
    max_retries: int = 3
    retry_count: int = 0
    status: TaskStatus          # PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
    result: dict | None
    error: str | None
    progress: float = 0.0
    depends_on: list[str]       # DAG edges
```

### 4.3 AgentMessage (Pydantic)

```python
class AgentMessage(BaseModel):
    message_id: str             # Auto-generated
    message_type: MessageType   # 12 types (peer, broadcast, request/response, etc.)
    sender_id: str
    recipient_id: str = ""      # Empty for broadcasts
    reply_to: str = ""
    topic: str = ""
    correlation_id: str = ""    # Links request→response
    in_reply_to: str = ""
    content: dict[str, Any]
    priority: MessagePriority   # LOW | NORMAL | HIGH | URGENT
    timestamp: str              # ISO-8601
    ttl_seconds: int = 300
```

### 4.4 AgentDirectoryEntry (dataclass)

```python
@dataclass
class AgentDirectoryEntry:
    agent_id: str
    agent_type: str = "sub_agent"
    capabilities: list[str]
    health: AgentHealthStatus   # HEALTHY | BUSY | DEGRADED | UNRESPONSIVE | TERMINATED
    active_tasks: int = 0
    max_concurrent_tasks: int = 3
    last_heartbeat: float
    registered_at: float
    metadata: dict[str, Any]
    performance: AgentPerformanceStats  # success_rate, avg_response_time
    user_id: str = ""
```

### 4.5 MongoDB Collections

| Collection | Key Fields | Indexes |
|------------|-----------|---------|
| `agents` | _id, user_id, agent_type, status | user_id, status |
| `tasks` | _id, agent_id, status, priority | (agent_id, status, priority) compound |
| `messages` | _id, from_agent_id, to_agent_id, status | agent_id, thread_id |
| `events` | _id, actor_id, event_type | actor_id, created_at |
| `capabilities` | _id, agent_id, name | agent_id |

### 4.6 Qdrant Collections

| Collection | Vector Dim | Payload Fields |
|------------|-----------|----------------|
| `user_interactions` | 1536 | user_id, agent_id, interaction_type, timestamp |
| `content_discoveries` | 1536 | user_id, agent_id, source, url, tags |
| `agent_knowledge` | 1536 | agent_id, knowledge_type, tags |

---

## 5. API Specifications

### 5.1 Core API (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/agents` | Create agent |
| GET | `/agents/{id}` | Get agent state |
| PUT | `/agents/{id}` | Update agent |
| DELETE | `/agents/{id}` | Delete agent |
| POST | `/agents/{id}/messages` | Send message |
| POST | `/agents/{id}/start` | Start event loop |
| POST | `/agents/{id}/stop` | Stop event loop |
| GET | `/agents` | List agents (by user, status) |
| POST | `/tasks` | Create task |
| GET | `/tasks/{id}` | Get task status |
| PUT | `/tasks/{id}` | Update task |
| DELETE | `/tasks/{id}` | Cancel task |
| POST | `/mcp` | MCP JSON-RPC endpoint |
| GET | `/mcp/manifest` | Tool manifest |
| GET | `/health` | Health check |

### 5.2 Communication Platform API (port 9000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/agents/register` | Register agent |
| POST | `/api/v1/agents/unregister` | Unregister agent |
| POST | `/api/v1/messages/send` | Route message |
| POST | `/api/v1/messages/broadcast` | Broadcast message |
| POST | `/api/v1/heartbeat` | Agent heartbeat |
| GET | `/api/v1/directory/agents` | List agents (?user_id, ?capability) |
| GET | `/api/v1/health` | Platform health |

See [PLATFORM_API.md](PLATFORM_API.md) for full request/response schemas.

---

## 6. Runtime Architecture

### 6.1 AgentRunner Event Loop (Full)

```python
async def run(self):
    await self._start_listeners()       # Redis inbox, heartbeat, comm hub
    while self._running:
        await self._process_messages()   # Poll queue → LLM → tools
        await self._process_tasks()      # Fetch pending → DAG → execute
        await self._maybe_checkpoint()   # Every 30s → MongoDB
        await asyncio.sleep(1)
```

**Message processing**:
1. Dequeue from `asyncio.Queue` (populated by Redis listener)
2. Build prompt: system + short-term memory + long-term context + incoming
3. Call LLM with tool definitions
4. If tool calls: execute via registry/MCP → feed results back → re-call LLM
5. Store interaction in short-term memory + Qdrant
6. Publish response to reply channel

### 6.2 LiteAgentRunner Event Loop (Lite)

```python
async def run(self):
    await self.start()                  # Register in directory, start comm hub
    while self._running:
        self.directory.heartbeat(...)   # Keep-alive
        await asyncio.sleep(1)
    # Message handling is callback-driven via InMemoryBroker
```

**Chat path**:
1. `chat(user_message)` → `PromptBuilder.build_agent_messages()`
2. Call LLM provider → get response
3. Append to `agent.short_term_memory` (trimmed to 50)
4. Return response

**Incoming message path**:
1. `InMemoryBroker.publish()` → invokes callback inline
2. `AgentCommunicationHub._handle_incoming()` → validates, dispatches
3. Handler builds prompt with `[Message from {sender}]: {content}`
4. Calls LLM → sends response back via `comm_hub.send()`

### 6.3 DAG Executor

```python
async def execute(self, executor_fn):
    graph, in_degree = self._build_graph()
    order = self._topological_sort(graph, in_degree)
    # Execute in waves: up to 5 concurrent tasks
    # On failure: mark descendants cancelled
    # Returns: dict[task_id → result]
```

### 6.4 Master Agent Orchestrator

```python
async def orchestrate_delegation(self, task_description):
    analysis = self.analyze_task_only(task_description)
    if not analysis["should_delegate"]:
        return await self._execute_direct(task_description)

    subtask_results = []
    for capability in analysis["suggested_sub_agents"]:
        # Build DelegationContext with prior results
        ctx = context_manager.build_context_for_sub_agent(...)
        # Delegate with timeout + circuit breaker
        result = await self._delegate_to_sub_agent(ctx)
        subtask_results.append(result)

    return await self._aggregate_results(task_description, subtask_results)
```

---

## 7. Broker Architecture

### 7.1 MessageBrokerProtocol

```python
class MessageBrokerProtocol(Protocol):
    async def publish(self, channel: str, message: dict) -> str: ...
    async def subscribe(self, channel: str, callback: Callable, ...) -> None: ...
    async def replay(self, channel: str, start_id: str = "0", count: int = 100) -> list[dict]: ...
```

### 7.2 Redis Streams Implementation (MessageBroker)

- Durable: messages survive subscriber downtime
- Consumer groups: at-least-once delivery with acknowledgment
- Dead-letter queue: after 5 failed delivery attempts
- Replay: read historical messages from any point
- Configurable retention: max 10,000 entries per channel

### 7.3 In-Memory Implementation (InMemoryMessageBroker)

- `asyncio`-based: callbacks invoked inline on publish
- Channel-scoped history: configurable max size (default 1000)
- Fan-out: all registered callbacks called for each message
- No consumer groups: all subscribers receive all messages
- Thread-safe within single event loop

---

## 8. LLM Integration

### 8.1 LLMRouter

```python
class LLMRouter:
    def __init__(self, settings):
        # Loads all available providers based on API keys
        self._providers = {"openai": ..., "gemini": ..., "anthropic": ..., "openrouter": ...}

    async def call(self, messages, config=None) -> LLMResult:
        provider = self._providers[config.get("llm_provider", self.default)]
        return await provider.chat(messages, config)
```

### 8.2 LLMResult

```python
@dataclass
class LLMResult:
    provider: str
    model: str
    content: str
    finish_reason: str | None
    usage: dict | None
    tool_calls: list[dict] | None  # [{name, arguments}]
```

### 8.3 PromptBuilder

Token-aware prompt construction with memory budget management:

```
System prompt (20% budget)
  → Agent role, capabilities, session context
Recent conversation (55% of remaining)
  → Relevance-scored short-term memory
Long-term context (45% of remaining)
  → Semantic search from Qdrant
Incoming message
  → User message or agent message
```

Emergency truncation if total exceeds model context window.

---

## 9. Tool System

### 9.1 Tool Definition

```python
class ToolDefinition:
    name: str
    description: str
    category: ToolCategory          # WEB | CODE | DATA | SYSTEM | COMMUNICATION
    parameters: list[ToolParameter]
    def to_openai_schema(self) -> dict    # For function calling
    def to_mcp_schema(self) -> dict       # For MCP protocol
```

### 9.2 Tool Execution

```python
class ToolRegistry:
    async def execute(self, name: str, arguments: dict) -> ToolResult:
        # Validate arguments → execute handler → return ToolResult
        # ToolResult: {success, result, error, execution_time_ms}
```

### 9.3 MCP Integration

- **MCPServer**: Exposes all registered tools via JSON-RPC 2.0
- **MCPClient**: Discovers and invokes tools from remote MCP servers
- Agent can use both local tools (registry) and remote tools (MCP)

---

## 10. Configuration

### 10.1 Settings (Pydantic BaseSettings)

```python
class Settings(BaseSettings):
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Databases
    mongo_dsn: str = "mongodb://mongodb:27017"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"

    # LLM
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None
    gemini_api_key: str | None
    gemini_api_keys: str | None      # Comma-separated for rotation
    anthropic_api_key: str | None
    openrouter_api_key: str | None

    # Limits
    max_concurrent_tasks_per_user: int = 25
    task_max_duration_seconds: int = 300
    task_max_retries: int = 3

    class Config:
        env_prefix = "JARVIS_"
```

---

## 11. Error Handling

| Layer | Strategy |
|-------|----------|
| LLM Calls | Retry with backoff; fallback provider (planned) |
| Tool Execution | Timeout per tool; result contains error field |
| Task Execution | max_retries with exponential backoff; cancel downstream on failure |
| Messaging | Dead-letter queue after 5 attempts; TTL expiry |
| Agent Loop | Continue after error; exponential backoff |
| Circuit Breaker | Open after 3 failures; half-open test after 60s |

---

## 12. Testing Strategy

| Level | Scope | Count |
|-------|-------|-------|
| Unit | Models, DAG executor, tools, circuit breaker, directory | 172+ |
| Integration | API flows, broker pub/sub, LLM calls | Included |
| Demo | `run_multi_agent_demo.py` — 4 scenarios end-to-end | 1 script |
| ASGI | Platform API via httpx ASGITransport | Inline |

Test frameworks: pytest with async support, factory fixtures.

---

## 13. Deployment

### 13.1 Docker Compose (Full)

```yaml
services:
  api-gateway:    # FastAPI, port 8000
  agent-runtime:  # Background agent loops
  task-executor:  # Celery workers
  mongodb:        # Port 27017
  redis:          # Port 6379
  qdrant:         # Port 6333
```

### 13.2 Standalone Scripts (Lite)

```bash
# Platform service
python run_platform.py --port 9000

# Single agent REPL
python run_agent.py --user kathir --model gemma-3-4b-it --provider gemini

# Multi-user demo
python run_multi_agent_demo.py --provider gemini --model gemma-3-4b-it
```

---

## 14. Security (Current State)

| Control | Status |
|---------|--------|
| Code execution sandboxing | Restricted builtins only (needs Docker) |
| API authentication | Placeholder JWT (needs implementation) |
| Secrets management | .env files (needs vault) |
| Transport encryption | None in dev (needs TLS) |
| Cross-user isolation | user_id filtering (needs enforcement) |
| Input validation | Pydantic on all API boundaries |

---

**Related Documents**:
- [HLD.md](HLD.md) — High-level architecture and design decisions
- [CLAUDE.md](CLAUDE.md) — System overview with component details
- [CURRENT_STATE.md](CURRENT_STATE.md) — Module-by-module status
- [PLATFORM_API.md](PLATFORM_API.md) — Platform API reference
