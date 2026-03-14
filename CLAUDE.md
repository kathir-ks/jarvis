# Jarvis Agent Platform - System Overview

> **For Claude AI Context** - This document provides a comprehensive overview of the Jarvis Agent Platform's purpose, architecture, components, and design.

> **📊 [Current State Assessment](CURRENT_STATE.md)** - For detailed module-by-module status, implementation progress, and quality ratings, see the current state document.

---

## 🎯 Application Purpose

**Jarvis** is a **multi-agent AI orchestration platform** designed to execute complex, multi-step tasks through autonomous AI agents that can:

- **Collaborate**: Multiple agents work together, with master agents delegating to specialized sub-agents
- **Use Tools**: Execute code, search the web, read URLs, perform calculations, and more
- **Maintain Memory**: Short-term (in-memory) and long-term (vector database) memory for context retention
- **Communicate**: Inter-agent messaging via Redis Streams or in-memory broker for real-time coordination
- **Execute Tasks**: DAG-based task execution with dependency management and parallel processing
- **Integrate via MCP**: Expose and discover tools through the Model Context Protocol
- **Run Anywhere**: Lite mode runs agents without MongoDB/Redis/Qdrant — ideal for demos and local development

### Use Cases
- Research tasks requiring web search and data aggregation
- Multi-step workflows with dependencies (e.g., research → plan → execute)
- Autonomous task delegation (master agent spawns specialized sub-agents)
- Complex decision-making requiring LLM reasoning with tool access
- **Multi-user agent deployment** — separate agents per user (kathir, akilesh, aswin) communicating via a shared platform

---

## 🏗️ System Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer (FastAPI)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ /agents  │  │ /tasks   │  │/messages │  │  /mcp    │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
└───────┼─────────────┼─────────────┼─────────────┼──────────────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │AgentService  │  │ TaskService  │  │ MCPServer    │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼──────────────────┼──────────────────┼─────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Runtime Layer                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Agent Runner (Event Loop)                     │  │
│  │  • Redis Pub/Sub Listener (messages)                      │  │
│  │  • MongoDB Task Poller (pending tasks)                    │  │
│  │  • LLM Integration (reasoning + tool calling)             │  │
│  │  • DAG Executor (parallel task execution)                 │  │
│  │  • Memory Management (short-term + long-term)             │  │
│  │  • Automatic Checkpointing                                │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              DAG Executor                                  │  │
│  │  • Topological sort (dependency resolution)               │  │
│  │  • Concurrent execution (up to 5 tasks in parallel)       │  │
│  │  • Failure propagation                                    │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Integration Layer                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │ LLM Router │  │Tool Registry│ │MCP Client  │                │
│  │ ┌────────┐ │  │ ┌────────┐ │  │            │                │
│  │ │ OpenAI │ │  │ │execute_│ │  │            │                │
│  │ │ Gemini │ │  │ │  code  │ │  │            │                │
│  │ │Anthropic│ │  │ │web_srch│ │  │            │                │
│  │ │OpenRoutr│ │  │ │read_url│ │  │            │                │
│  │ └────────┘ │  │ │calcultr│ │  │            │                │
│  │            │  │ │get_time│ │  │            │                │
│  └────────────┘  └────────────┘  └────────────┘                │
└─────────────────────────────────────────────────────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data/Infrastructure Layer                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │  MongoDB   │  │   Redis    │  │  Qdrant    │                │
│  │ (Agents &  │  │ (Streams & │  │  (Vector   │                │
│  │   Tasks)   │  │  Messaging)│  │   Memory)  │                │
│  └────────────┘  └────────────┘  └────────────┘                │
│                   OR                                             │
│  ┌──────────────────────────────────────────────┐               │
│  │  Lite Mode (zero infrastructure)             │               │
│  │  InMemoryBroker + InMemoryAgentRepository    │               │
│  └──────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### Multi-User Platform Topology

```
             PRODUCTION TOPOLOGY (future)

  ┌────────────────────────────────────────────────┐
  │     COMMUNICATION PLATFORM (port 9000)         │
  │  ┌──────────────┐  ┌──────────────────────┐   │
  │  │ MessageBroker│  │ AgentDirectory       │   │
  │  │ (InMemory or │  │ (user-aware)         │   │
  │  │  Redis)      │  │                      │   │
  │  └──────────────┘  └──────────────────────┘   │
  │  ┌────────────────────────────────────────┐   │
  │  │ REST API: /register, /send, /poll, /dir│   │
  │  └────────────────────────────────────────┘   │
  └────────────────────┬───────────────────────────┘
                       │ HTTP
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  ┌───────────┐  ┌───────────┐  ┌───────────┐
  │ kathir's  │  │ akilesh's │  │ aswin's   │
  │ Runner    │  │ Runner    │  │ Runner    │
  │ (proc 1)  │  │ (proc 2)  │  │ (proc 3)  │
  └───────────┘  └───────────┘  └───────────┘

              DEV/DEMO MODE (single process)

  ┌──────────────────────────────────────────────┐
  │  Shared InMemoryBroker + AgentDirectory      │
  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
  │  │ kathir's │  │akilesh's │  │ aswin's  │  │
  │  │ runner   │  │ runner   │  │ runner   │  │
  │  └──────────┘  └──────────┘  └──────────┘  │
  │  All via InMemoryBroker — zero network I/O  │
  └──────────────────────────────────────────────┘
```

---

## 📦 Core Components

### 1. **Agent Entity** (`jarvis/app/runtime/agent.py`)

**Purpose**: Represents an autonomous AI agent with state, memory, and configuration.

**Key Features**:
- **State Machine**: `IDLE → RUNNING → WAITING_APPROVAL → ERROR/TERMINATED`
- **Agent Types**:
  - `MASTER`: Can spawn and manage sub-agents
  - `SUB_AGENT`: Specialized agent for specific tasks
- **Memory System**:
  - Short-term: Last 50 interactions in-memory
  - Long-term: Vector embeddings in Qdrant for semantic search
  - Episodic: Task history and outcomes
- **Configuration**:
  - LLM provider (OpenAI, Gemini, Anthropic)
  - Model selection and parameters (temperature, max_tokens)
  - Loop intervals and checkpoint frequency
  - MCP server URL (optional) for tool discovery
- **Context Management**: Session state dictionary for stateful conversations

### 2. **Task Entity** (`jarvis/app/runtime/task.py`)

**Purpose**: Represents work units that agents execute.

**Key Features**:
- **Task Types**: `RESEARCH`, `EXPLORATION`, `PURCHASE`, `BOOKING`, `CUSTOM`
- **Status Flow**: `PENDING → RUNNING → COMPLETED/FAILED/CANCELLED`
- **Execution Controls**:
  - `max_duration`: Timeout for task execution
  - `max_retries`: Automatic retry on failure
  - `priority`: 1-10 scale for execution order
- **Dependencies**: DAG support via `depends_on` list
- **Callbacks**: Hooks for completion, failure, and progress events
- **Retry Logic**: Exponential backoff with configurable max retries

### 3. **Agent Runner** (`jarvis/app/runtime/agent_runner.py`)

**Purpose**: Event loop that drives agent execution.

**Event Loop Cycle** (runs every 1 second):

```python
1. Process Messages
   ├─ Poll Redis inbox: agent:{agent_id}:inbox
   ├─ Build prompt with message + context + memory
   ├─ Call LLM with tool definitions
   ├─ Handle tool calls if present
   └─ Store interaction in memory (short + long-term)

2. Process Tasks
   ├─ Fetch pending tasks from MongoDB (priority-sorted)
   ├─ Build DAG from task dependencies
   ├─ Execute DAG with concurrency limit (5 parallel)
   └─ Update task statuses and results

3. Checkpoint
   ├─ Check if checkpoint interval elapsed (30s default)
   ├─ Save agent state to MongoDB
   └─ Persist context and task metadata

4. Sleep (1s)
```

**Key Features**:
- **MCP Integration**: Can discover and invoke tools via MCP protocol
- **Tool Execution**: Direct registry or MCP-based tool invocation
- **Memory Consolidation**: Automatic short → long-term memory transfer
- **Graceful Shutdown**: `stop()` and `terminate()` methods
- **Error Recovery**: Continues after errors with exponential backoff

### 4. **DAG Executor** (`jarvis/app/runtime/dag_executor.py`)

**Purpose**: Executes tasks in dependency order with parallelism.

**Algorithm**:
```
1. Topological Sort
   └─ Build execution order respecting dependencies

2. Concurrent Execution
   ├─ Execute up to 5 tasks in parallel
   ├─ Wait for dependencies before starting task
   └─ Collect results as tasks complete

3. Failure Handling
   ├─ Mark failed tasks as FAILED
   ├─ Cancel all downstream dependent tasks
   └─ Continue executing independent branches
```

### 5. **LLM Gateway** (`jarvis/app/llm/`)

**Purpose**: Unified interface for multiple LLM providers.

**Components**:
- **LLMRouter** (`router.py`): Routes requests to configured provider
- **Providers**:
  - `OpenAIProvider`: GPT-4, GPT-3.5 models
  - `GeminiProvider`: Gemini 1.5 Pro, Flash models
  - `AnthropicProvider`: Claude models (interface defined)
- **Tool Calling Support**: All providers support function calling
- **Structured Output**: Returns `LLMResult` with content, metadata, tool calls

### 6. **Tool Registry** (`jarvis/app/llm/tool_registry.py`)

**Purpose**: Centralized registry for tool discovery and execution.

**Current Tools**:
- `execute_code`: Run Python code in isolated environment
- `get_time`: Get current time/date
- `calculator`: Evaluate mathematical expressions
- `web_search`: Search the web (DuckDuckGo/SerpAPI)
- `read_url`: Fetch and parse webpage content

**Features**:
- OpenAI-compatible function schemas
- Type validation for tool arguments
- Async execution support
- Result tracking (success/failure, execution time)

### 7. **MCP Protocol** (`jarvis/app/mcp/`)

**Purpose**: Model Context Protocol implementation for tool exposure and discovery.

**Components**:
- **MCPServer** (`server.py`):
  - Exposes tools via JSON-RPC 2.0 protocol
  - Handles: `initialize`, `tools/list`, `tools/call`, `ping`
  - Converts tool registry to MCP format
- **MCPClient** (`client.py`):
  - Discovers tools from remote MCP servers
  - Invokes tools via HTTP
  - Caches tool definitions
  - Graceful fallback to direct registry
- **Protocol** (`protocol.py`):
  - Request/Response dataclasses
  - Error codes and handling
  - Tool schemas and results

### 8. **Vector Memory** (`jarvis/app/db/vector_memory.py`)

**Purpose**: Long-term memory with semantic search.

**Features**:
- Stores interactions as vector embeddings in Qdrant
- Similarity search for relevant context retrieval
- Automatic embedding generation (OpenAI/local models)
- Time-weighted relevance scoring
- Memory consolidation from short-term storage

### 9. **Messaging System** (`jarvis/app/messaging/`)

**Purpose**: Inter-agent communication via Redis Streams or in-memory broker.

**Components**:
- **MessageBrokerProtocol** (`broker_interface.py`): Abstract protocol for broker implementations
- **MessageBroker** (`broker.py`): Redis Streams-backed durable broker (production)
- **InMemoryMessageBroker** (`jarvis/app/lite/memory_broker.py`): `asyncio`-based drop-in (demo/dev)

**Features**:
- Message routing to agent inboxes
- Broadcast messaging
- Request-response patterns
- Message persistence (optional)

### 10. **Database Repositories** (`jarvis/app/db/repositories.py`)

**AgentRepository**:
- CRUD operations for agents
- Status updates with timestamps
- Checkpoint persistence
- Query by user, parent agent
- Sub-agent retrieval

**TaskRepository**:
- CRUD operations for tasks
- Priority-based queries
- Status transitions
- Retry tracking
- Dependency queries

### 11. **Lite Infrastructure** (`jarvis/app/lite/`)

**Purpose**: Zero-dependency replacements for MongoDB/Redis/Qdrant, enabling agents to run without any external services.

**Components**:
- **InMemoryMessageBroker** (`memory_broker.py`): `asyncio.Queue`-based broker with publish/subscribe/replay
- **InMemoryAgentRepository** (`memory_repo.py`): Dict-backed agent CRUD with same async API as `AgentRepository`

### 12. **LiteAgentRunner** (`jarvis/app/runtime/lite_agent_runner.py`)

**Purpose**: Lightweight agent event loop that replaces the full `AgentRunner` for infrastructure-free operation.

**Key Features**:
- Constructor injection of broker, LLM provider, directory (no global singletons)
- Interactive `chat()` method for direct user interaction
- Auto-responds to incoming peer/broadcast messages via the LLM
- Registers in `AgentDirectory` with `user_id` for multi-user filtering
- Heartbeat broadcasting in background `run()` loop
- All memory kept in-process on the `Agent` object (no Qdrant needed)

### 13. **Communication Platform** (`jarvis/app/platform/`)

**Purpose**: Standalone multi-agent messaging and discovery service.

**Components**:
- **CommunicationPlatformService** (`service.py`): Business logic wrapping broker + directory
- **Platform API** (`api.py`): FastAPI router with 7 REST endpoints
- **Pydantic Models** (`models.py`): Request/response schemas
- **App Factory** (`app.py`): `create_platform_app()` for standalone or embedded use

**API Endpoints** (port 9000):
- `POST /api/v1/agents/register` — Register agent with user_id, capabilities
- `POST /api/v1/agents/unregister` — Remove agent from directory
- `POST /api/v1/messages/send` — Route message between agents
- `POST /api/v1/messages/broadcast` — Broadcast to all agents or topic
- `POST /api/v1/heartbeat` — Agent health heartbeat
- `GET  /api/v1/directory/agents` — List agents (filter by user_id, capability)
- `GET  /api/v1/health` — Platform health status

### 14. **Entry Points** (root-level scripts)

- **`run_platform.py`**: Starts Communication Platform as standalone FastAPI service
- **`run_agent.py`**: Starts a single `LiteAgentRunner` with interactive REPL
- **`run_multi_agent_demo.py`**: Single-process demo — 3 agents for kathir, akilesh, aswin with shared `InMemoryBroker`

---

## 🔄 High-Level Flow & Design

### Flow 1: Agent Message Processing

```
User sends message
    ↓
POST /agents/{agent_id}/messages
    ↓
Publish to Redis: agent:{agent_id}:inbox
    ↓
Agent Runner polls inbox
    ↓
Build prompt with:
  - Message content
  - Agent context (session state)
  - Short-term memory (last 50 interactions)
  - Long-term memory (semantic search from Qdrant)
    ↓
Call LLM Router with:
  - Messages array
  - Available tools (from registry or MCP)
  - Agent configuration (model, temperature, etc.)
    ↓
LLM Response (may include tool calls)
    ↓
If tool calls present:
  ├─ Execute each tool (via registry or MCP)
  ├─ Collect results
  └─ Send results back to LLM for final response
    ↓
Store interaction in memory:
  ├─ Add to short-term memory buffer
  └─ Generate embedding and store in Qdrant
    ↓
Return response to user
```

### Flow 2: Task Execution

```
User submits task
    ↓
POST /agents/{agent_id}/tasks
    ↓
TaskRepository.create(task) → MongoDB
    ↓
Agent Runner polls pending tasks (priority-sorted)
    ↓
Build DAG from task dependencies
    ↓
DAG Executor:
  ├─ Topological sort
  ├─ Execute up to 5 tasks in parallel
  ├─ For each task:
  │   ├─ Build prompt with task description
  │   ├─ Call LLM with tools
  │   ├─ Execute tool calls
  │   ├─ Mark task as COMPLETED/FAILED
  │   └─ Store result in MongoDB
  └─ Handle failures (cancel downstream tasks)
    ↓
Return task results
```

### Flow 3: Master-SubAgent Delegation (Phase 4 - Planned)

```
Master Agent receives complex task
    ↓
Master analyzes task complexity
    ↓
Master spawns specialized SubAgents:
  ├─ ResearchAgent (for web research)
  ├─ CodeAgent (for code execution)
  └─ PlanningAgent (for task planning)
    ↓
Master distributes subtasks via messaging
    ↓
SubAgents execute in parallel:
  ├─ Each SubAgent has own event loop
  ├─ SubAgents use specialized tools
  └─ SubAgents report progress to Master
    ↓
Master aggregates results
    ↓
Master returns final result to user
```

### Flow 4: MCP Tool Discovery & Execution

```
Agent initialization with mcp_server_url
    ↓
MCPClient connects to server
    ↓
MCPClient.initialize()
  ├─ GET server info
  └─ Receive capabilities
    ↓
MCPClient.list_tools()
  ├─ Fetch tool definitions
  └─ Cache tools locally
    ↓
Agent builds LLM config with MCP tools
    ↓
LLM requests tool execution
    ↓
MCPClient.call_tool(name, arguments)
  ├─ POST to MCP server
  ├─ Server executes via ToolRegistry
  └─ Return result to agent
    ↓
Agent processes tool result
    ↓
Agent sends result back to LLM
```

---

## 🛠️ Technology Stack

### Backend
- **Framework**: FastAPI (async Python web framework)
- **Language**: Python 3.11+
- **Type System**: Pydantic (data validation and serialization)

### Databases
- **MongoDB**: Agent state, tasks, and metadata (Motor async driver)
- **Redis**: Message broker for Pub/Sub and caching
- **Qdrant**: Vector database for long-term memory embeddings

### AI/ML
- **LLM Providers**:
  - OpenAI (GPT-4, GPT-3.5)
  - Google Gemini (Gemini 1.5 Pro/Flash)
  - Anthropic Claude (interface ready)
- **Embeddings**: OpenAI text-embedding-3-small (or local models)

### Infrastructure
- **Containerization**: Docker & Docker Compose
- **Task Queue**: Celery (async task execution)
- **HTTP Client**: httpx (async HTTP for MCP)
- **Protocol**: Model Context Protocol (MCP) for tool exposure

### Development
- **Testing**: pytest with async support
- **Logging**: Python logging with structured output
- **Environment**: python-dotenv for configuration

---

## 📊 Implementation Status

### ✅ Completed (75% overall)

**Phase 1: Basic Agent Runtime**
- ✅ Vector Memory Service (Qdrant integration)
- ✅ LLM Integration (OpenAI, Gemini)
- ✅ Agent Lifecycle & Event Loop

**Phase 2: Tool Integration**
- ✅ Tool Schema (OpenAI-compatible)
- ✅ Core Tools (5 tools implemented)
- ✅ LLM Tool Calling Integration

**Phase 3: MCP Protocol**
- ✅ MCP Server (protocol handler)
- ✅ MCP Tool Registration (5 tools)
- ✅ Agent MCP Integration (discovery & execution)
- ✅ MCP Client (HTTP-based with fallback)

**Phase 4: Agent-to-Agent Communication**
- ✅ Agent Discovery (shared registry, capability queries)
- ✅ Message Protocol (typed envelopes, peer-to-peer, broadcast)
- ✅ Collaboration Patterns (master-subagent delegation)
- ✅ Circuit Breaker (prevents cascading failures)
- ✅ Agent Directory (health-aware load-balanced selection)
- ✅ Heartbeat-based health monitoring

**Phase 5: Multi-User Platform**
- ✅ MessageBrokerProtocol abstraction
- ✅ InMemoryMessageBroker (zero-infra drop-in)
- ✅ InMemoryAgentRepository (dict-backed)
- ✅ LiteAgentRunner (lightweight event loop)
- ✅ Communication Platform service + REST API
- ✅ Multi-user demo (kathir, akilesh, aswin)
- ✅ Entry points (run_platform, run_agent, run_multi_agent_demo)

### 🔮 Future Enhancements
- HttpPlatformBroker (multi-process agent deployment over HTTP)
- Browser automation (Playwright integration)
- E-commerce adapters
- Authentication & authorization
- Advanced task scheduling
- Monitoring & observability (Prometheus, OpenTelemetry)
- Multi-tenancy support

---

## 🚀 Quick Reference

### Key Files

```
jarvis/app/
├── runtime/
│   ├── agent.py              # Agent entity and state machine
│   ├── task.py               # Task entity and lifecycle
│   ├── agent_runner.py       # Event loop (full — requires MongoDB/Redis)
│   ├── lite_agent_runner.py  # Event loop (lite — zero infrastructure)
│   ├── agent_directory.py    # Health-aware agent registry (user_id support)
│   ├── agent_communication.py # Peer-to-peer + broadcast messaging hub
│   ├── circuit_breaker.py    # Per-agent circuit breaker with backoff
│   ├── delegation_context.py # Context propagation for sub-agents
│   ├── master_agent.py       # Master agent orchestration
│   ├── task_analyzer.py      # Task complexity analysis
│   ├── agent_capabilities.py # Capability registry
│   └── dag_executor.py       # Dependency resolution & parallel execution
│
├── llm/
│   ├── router.py             # LLM provider routing
│   ├── tool_registry.py      # Tool discovery & execution
│   ├── prompt_builder.py     # Prompt construction (token-aware)
│   ├── providers/
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py
│   │   ├── anthropic_provider.py
│   │   └── openrouter_provider.py
│   └── tools/
│       ├── core_tools.py     # execute_code, calculator, get_time
│       └── web_tools.py      # web_search, read_url
│
├── lite/                     # Zero-infrastructure implementations
│   ├── memory_broker.py      # In-memory message broker (asyncio)
│   └── memory_repo.py        # In-memory agent repository (dict)
│
├── platform/                 # Communication Platform service
│   ├── app.py                # FastAPI app factory
│   ├── api.py                # REST API routes
│   ├── service.py            # Platform business logic
│   └── models.py             # Pydantic request/response models
│
├── mcp/
│   ├── server.py             # MCP server implementation
│   ├── client.py             # MCP client for tool discovery
│   └── protocol.py           # MCP protocol definitions
│
├── db/
│   ├── repositories.py       # MongoDB repositories
│   ├── vector_memory.py      # Qdrant vector store
│   └── mongo_client.py       # MongoDB connection
│
├── messaging/
│   ├── broker.py             # Redis Streams messaging (production)
│   └── broker_interface.py   # MessageBrokerProtocol abstraction
│
└── api/routes/
    ├── agents.py             # Agent CRUD & control
    ├── tasks.py              # Task management
    └── mcp.py                # MCP endpoints

# Root entry points
run_platform.py               # Start Communication Platform (port 9000)
run_agent.py                   # Start single agent REPL
run_multi_agent_demo.py        # Multi-user demo (3 agents, zero infra)
run_gemma_agents.py            # Standalone Gemma agent demo
```

### Core Concepts

1. **Agent**: Autonomous AI entity with memory, tools, and reasoning
2. **Task**: Unit of work with dependencies and execution controls
3. **Event Loop**: Continuous cycle of message processing, task execution, and checkpointing
4. **DAG**: Directed Acyclic Graph for task dependency management
5. **Tool**: Function callable by LLM for external actions
6. **MCP**: Protocol for tool discovery and remote execution
7. **Memory**: Short-term (buffer) + Long-term (vector embeddings)
8. **Messaging**: Redis Streams or InMemoryBroker for inter-agent communication
9. **Communication Platform**: Standalone service for multi-user agent messaging
10. **LiteAgentRunner**: Infrastructure-free agent runner for demos and development

---

## 📝 Notes for Claude AI

- This is a **multi-agent orchestration platform** similar to AutoGPT/LangChain agents
- The **agent runner event loop** is the heart of the system — two variants:
  - `agent_runner.py`: Full runner (requires MongoDB, Redis, Qdrant)
  - `lite_agent_runner.py`: Lightweight runner (zero external infrastructure)
- **Tools** are the primary way agents interact with the external world
- **MCP** enables tool discovery from remote servers and tool sharing
- **Phase 4 is complete**: Full multi-agent collaboration with peer messaging, circuit breakers, and load balancing
- **Phase 5 is complete**: Multi-user Communication Platform with `LiteAgentRunner` and REST API
- The system uses **async/await** throughout for non-blocking I/O
- **Full mode**: MongoDB stores persistent state, Redis handles messaging, Qdrant provides vector search
- **Lite mode**: Everything runs in-memory — ideal for demos and local development
- **Multi-user**: Agents are owned by users (`user_id`); the directory supports user-scoped queries

### When Making Changes
1. Maintain async patterns throughout
2. Update tests when adding new tools
3. Keep MCP protocol compatibility
4. Follow the established repository pattern
5. Add proper error handling and logging
6. Update IMPLEMENTATION.md with progress
7. **Update CURRENT_STATE.md** whenever significant changes or progress has been made:
   - New modules or components added
   - Major features completed or refactored
   - Implementation status changes (e.g., Phase completion)
   - Critical bugs fixed or security improvements
   - Architecture changes or design decisions
   - Update module status, quality ratings, and gaps sections

---

**Last Updated**: March 14, 2026
**Version**: 0.5.0-beta
**Status**: Phase 5 Complete — Multi-User Communication Platform
