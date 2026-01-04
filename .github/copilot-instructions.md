# Jarvis Agent Platform - AI Coding Instructions

## Project Overview

This is a **personal AI agent platform** (Jarvis) that creates autonomous agents for users. Agents perform tasks like research, e-commerce, booking, and proactive content discovery. The project is currently in the **design phase** with `HLD.txt` (High-Level Design) and `Requirement.txt` as primary documentation.

## Architecture Summary

### Core Components (from HLD.txt)

| Component | Purpose |
|-----------|---------|
| **Agent Runtime** | Event loop executing agents with DAG-based parallel/sequential task execution |
| **Task Executor** | Isolated task execution (sandboxed Python → containers later) |
| **Agent Message Channel** | Inter-agent communication via Redis Pub/Sub (→ RabbitMQ at scale) |
| **Platform Orchestrator** | Lifecycle management, user/agent management, scheduling |
| **LLM Gateway** | Abstraction layer routing to GPT-4/Claude/Gemini with tool registry |

### Decided Technology Stack

- **Language**: Python 3.11+
- **Framework**: FastAPI (async-native, Pydantic validation)
- **Database**: MongoDB Atlas (flexible schema, change streams)
- **Vector DB**: Qdrant (self-hosted) or Pinecone
- **Cache/Queue**: Redis (multi-purpose: cache, Celery backend, pub/sub)
- **Task Queue**: Celery + Redis
- **Browser Automation**: Playwright
- **LLM Integration**: Custom abstraction + LangChain
- **Deployment**: Docker Compose (MVP) → Kubernetes (production)

## Key Design Decisions

1. **Agent execution**: Spin up on-demand, but agents run in "auto-pilot" mode exploring on behalf of users
2. **Task isolation**: Sandboxed Python for MVP, containerized later
3. **State persistence**: Every action/memory/task update persists to DB immediately (crash recovery)
4. **Concurrency**: DAG-based execution graph for parallel/sequential task dependencies
5. **Max concurrent tasks**: 25 per user (configurable)
6. **Message handling**: Event-driven (platform notifies agents)
7. **Data retention**: Keep forever

## Agent Entity Structure

When implementing agents, include these core properties:
```python
# Identity: agent_id, agent_type (MASTER|SUB_AGENT), parent_agent_id, user_id
# State: status (IDLE|RUNNING|WAITING_APPROVAL|ERROR|TERMINATED)
# Memory: short_term_memory, long_term_memory (vector DB), episodic_memory
# Execution: task_queue (priority queue), tools_available (Map)
```

## Task Schema Requirements

Tasks must be **idempotent** (safe to retry). Required fields:
- `task_type`: RESEARCH | EXPLORATION | PURCHASE | BOOKING | CUSTOM
- `max_duration`: Default 300 seconds
- `max_retries`: Default 3
- Callbacks: `on_complete`, `on_failure`, `on_progress`

## Cross-User Communication

Messages between different users' agents require **approval workflow**:
1. Check recipient's privacy settings
2. If approval required → send approval request to recipient user
3. Only deliver after explicit consent

## Development Guidelines

- Use **async/await** throughout—LLM calls are I/O-bound (1-10 seconds)
- All external integrations use the **Adapter Interface** pattern:
  ```python
  authenticate(credentials) -> auth_token
  search(query) -> List[SearchResult]
  get_details(item_id) -> ItemDetails
  perform_action(action_type, params) -> ActionResult
  ```
- Agent state changes trigger **checkpoint()** for crash recovery
- Use **Motor** (async MongoDB driver) for database operations

## Open Questions (Defer Implementation)

These items are marked "Decided Later" in HLD—avoid implementing until specified:
- LLM cost management / per-user budgets
- Database sharding/replication strategy
- Specific cloud provider deployment details
- Data backup/disaster recovery procedures

## File Reference

- `Requirement.txt`: Primary objectives, capabilities, functional/non-functional requirements
- `HLD.txt`: Complete architecture, component design, technology justification, system flows
