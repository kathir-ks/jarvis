# Jarvis Agent Platform — Low-Level Design (MVP)

## 1. Scope & Goals
- MVP delivers always-on personal agents with auto-pilot exploration, task execution, and cross-agent messaging.
- Prioritize reliability, persistence, idempotent tasks, and privacy approval for cross-user messaging.
- Out of scope for MVP: multi-cloud, cost governance, DR/backup automation, advanced LLM cost routing, sharding.

## 2. Runtime Topology (MVP)
- Services (Docker Compose):
  - `api-gateway` (FastAPI + Uvicorn): auth, REST, orchestrator façade.
  - `agent-runtime` (FastAPI worker or background process): runs Agent event loops, uses Redis Pub/Sub + Mongo.
  - `task-executor` (Celery worker pool): executes isolated tasks; Redis broker + backend.
  - `mongodb`: primary datastore (Motor client from services).
  - `redis`: cache, Celery broker/backend, pub/sub for messaging.
  - `qdrant`: vector DB for memory retrieval.
- Networking: all services on internal Docker network; `api-gateway` exposes port 8000.

## 3. Project Structure (Python 3.11, FastAPI)
```
jarvis/
  app/
    api/                # Routers, dependencies
    core/               # Settings, logging, middleware
    models/             # Pydantic DTOs
    services/           # Orchestrator facades
    runtime/            # Agent runtime loop, DAG executor
    tasks/              # Celery task definitions
    messaging/          # Pub/Sub client, message router
    llm/                # LLM gateway, tool registry
    integrations/       # Adapters, browser automation
    db/                 # Mongo/Qdrant clients, repositories
    utils/
  docker/
    docker-compose.yml
    env.example
```

## 4. Core Data Models (MongoDB)
- `users`: { `_id`, `email`, `auth_provider`, `profile`, `created_at`, `plan`, `settings` }
- `agents`: { `_id`, `user_id`, `agent_type`, `parent_agent_id`, `status`, `config`, `context`, `tools_available`, `last_checkpoint`, `short_term_memory_ref`, `long_term_memory_ref`, `task_queue_meta`, `created_at`, `updated_at` }
- `tasks`: { `_id`, `agent_id`, `parent_task_id`, `task_type`, `task_description`, `task_params`, `priority`, `llm_config`, `tools`, `max_duration`, `max_retries`, `status`, `created_at`, `started_at`, `completed_at`, `result`, `error`, `progress` }
- `messages`: { `_id`, `from_agent_id`, `from_user_id`, `to_agent_id`, `to_user_id`, `message_type`, `message_body`, `metadata`, `timestamp`, `expires_at`, `status`, `requires_approval`, `approved_by_user` }
- `events`: { `_id`, `actor_type`, `actor_id`, `event_type`, `payload`, `created_at`, `severity`, `correlation_id` }
- Vector store (Qdrant):
  - `user_interactions`: vector=embedding(text), payload={ `user_id`, `agent_id`, `message_id`, `type`, `timestamp` }
  - `content_discoveries`: vector=embedding(content), payload={ `user_id`, `agent_id`, `source`, `url`, `tags`, `timestamp` }
- Indexing: Mongo indexes on `agent_id`, `user_id`, `status`, `message_id`, `created_at`; TTL on `messages.expires_at` (optional later); compound index `tasks(agent_id, status, priority)`.

## 5. API Surface (FastAPI)
- Auth (placeholder): `/auth/login`, `/auth/refresh` (JWT/OAuth2 planned; use stub for dev).
- Agents:
  - `POST /agents` create master/sub-agent.
  - `GET /agents/{agent_id}` fetch state.
  - `POST /agents/{agent_id}/checkpoint` persist context.
  - `POST /agents/{agent_id}/terminate` shutdown.
- Tasks:
  - `POST /agents/{agent_id}/tasks` submit task (schema below).
  - `GET /tasks/{task_id}` status/result.
  - `POST /tasks/{task_id}/cancel` request cancel.
- Messaging:
  - `POST /messages` send message (validates privacy rules).
  - `GET /messages/history?agent_id=&thread_id=` paginated history.
- Discovery (optional MVP stub): `POST /agents/{agent_id}/discover` triggers exploration task.
- Health/ops: `/health`, `/metrics` (Prometheus), `/version`.

### API Layer Responsibilities
- Routers only orchestrate services; no DB writes directly.
- Dependency-injected services handle validation and repository calls.
- Idempotency: use `Idempotency-Key` header for task/message submission; dedupe by key stored in Mongo.

### Request Schemas (Pydantic)
- CreateAgent: { `agent_type`, `parent_agent_id?`, `config`, `tools_enabled?` }
- SubmitTask: { `task_type`, `task_description`, `task_params`, `priority?`, `llm_config?`, `tools?`, `max_duration?`, `max_retries?`, `on_complete?`, `on_failure?`, `on_progress?` }
- SendMessage: { `from_agent_id`, `to_agent_id`, `message_type`, `message_body`, `metadata`, `requires_approval?` }

### Response Schemas
- Standard envelope: `{ "request_id": str, "data": <payload>, "error": {code, message}? }`.
- Pagination: cursor-based for history lists `{ "data": [...], "next_cursor": str? }`.

## 6. Agent Runtime (async)
- Components: `Agent` entity, `AgentRunner` loop, `DAGExecutor`, `CheckpointManager`, `ToolInvoker`, `MemoryManager`.
- Event Loop (non-blocking):
  1) poll Redis Pub/Sub inbox for messages → handle `receive_message()`.
  2) poll Mongo task queue view (`tasks` by `agent_id` status=PENDING) → build DAG from dependencies (if provided).
  3) execute runnable DAG nodes concurrently (async tasks); submit long jobs to `task-executor`.
  4) periodically `checkpoint()` → persist `context`, `task_queue_meta`, `last_checkpoint`.
  5) sleep small interval (configurable, default 1s) or await pub/sub notifications.
- State machine: `IDLE -> RUNNING -> WAITING_APPROVAL -> RUNNING -> COMPLETED | ERROR | TERMINATED`; approval gating triggered by incoming approvals.
- Memory:
  - short-term: recent messages cached in Redis and persisted snapshot in Mongo.
  - long-term: embeddings in Qdrant keyed by `user_id`/`agent_id`.
  - episodic: append task executions to Mongo `events` and `tasks.result`.
- Tool invocation:
  - registry per agent (`tools_available`); validate before call; execute with timeout; offload blocking tools to Celery via `execute_tool_call` task; return `ToolResult` with `status`, `payload`, `error`.
- Sub-agent spawning: API call creates new agent record; runtime registers child; parent tracks `parent_agent_id` relation.

### DAG Executor
- Input: list of runnable tasks with dependencies; topological sort; run ready nodes concurrently with asyncio.gather.
- Backpressure: cap concurrent nodes per agent; queue overflow defers to next tick.
- Failure policy: on node failure, mark downstream nodes cancelled unless flagged `continue_on_fail`.

### Checkpointing
- Triggered by timer (default 30s) or critical mutations (task status change, memory write).
- Stored fields: `agent_context`, `task_queue_meta`, `last_checkpoint`, `short_term_memory_snapshot_ref`.
- On restart: reload agent from Mongo, repopulate short-term cache from snapshot, resubscribe to inbox channel.

## 7. Task Executor (Celery)
- Celery config: broker=`redis://`, backend=`redis://`, acks_late=true, prefetch=1, soft/hard time limits (`max_duration`), retry policy (max_retries default 3, exponential backoff).
- Task wrapper flow:
  1) Accept `task_id`, fetch spec from Mongo.
  2) Execute `execute()` function (per `task_type` module) in isolated process.
  3) Honor `max_duration` via Celery time limits.
  4) On success: persist `result`, `status=COMPLETED`, trigger callback (publish Redis event to agent inbox).
  5) On failure: record `error`, increment retry count; if retries exhausted → `FAILED` and callback.
- Isolation: process-level (Celery worker pool) for MVP; container-level later.
- Resource caps (MVP): worker concurrency env var; memory monitored via OS limits if needed.

### Task Modules (examples)
- `research.execute`: web search + summarization; stores excerpts to Qdrant.
- `exploration.execute`: browse via Playwright, extract entities, emit discoveries.
- `purchase.execute`: stub; requires approval flag; currently logs intent only.
- `booking.execute`: stub; same approval requirements as purchase.

### Cancellation
- API sets `status=CANCELLED_REQUESTED`; worker checks flag at safe points; if cancelled, record partial progress and exit.

## 8. Messaging System (Redis Pub/Sub → RabbitMQ later)
- Channel naming: `agent:<agent_id>:inbox` for delivery; `system:approvals` for approval workflows.
- Send flow:
  1) API validates sender, privacy; if cross-user and approval required → enqueue approval message to recipient user.
  2) Publish message to recipient inbox; persist record in Mongo `messages` with status `PENDING` → update to `DELIVERED` on publish ack; agent updates to `READ` on consume.
- Delivery guarantee: at-least-once (Pub/Sub + durable store). Idempotency via `message_id` in handlers.
- Privacy: check `to_user` settings before publish; if pending approval, agent runtime waits in `WAITING_APPROVAL`.

### Message State Transitions
- `PENDING -> DELIVERED -> READ`; `FAILED` on publish error; TTL expiry optional.
- Approval: `requires_approval=true` adds `APPROVAL_REQUESTED`; on approval, resume delivery and clear hold.

## 9. LLM Gateway & Tools
- LLM router: providers list (OpenAI/Anthropic/Gemini) configurable; simple round-robin + fallback on errors; timeouts per call.
- Tool registry: typed schema for tool inputs; validate before dispatch; tools include web search, browser automation (Playwright), scraping, e-commerce adapter calls.
- Prompt manager: store templates in code (YAML or Python dict) with versions; include system prompts per agent type.
- Token tracking (placeholder): log tokens per call; no enforcement MVP.

### LLM Call Policy
- Timeouts per call; retries up to 2 with backoff on transient errors.
- Guardrails: max tokens per call; redact secrets before logging; store prompts optionally for debugging behind flag.

## 10. Integrations
- Adapter interface (per HLD): authenticate/search/get_details/perform_action.
- Browser automation: Playwright launched from Celery tasks; headless chromium; respect `max_duration`.
- Credential vault (MVP stub): encrypted secrets in environment (.env) for dev; interface `CredentialStore` to swap later.

### Adapter Packaging
- Each adapter module exposes `adapter.yaml` describing capabilities; registry loads and validates at startup.
- Versioning via semantic version string in adapter metadata; incompatible changes require bump.

## 11. Deployment (Docker Compose)
- Services: `api-gateway`, `agent-runtime`, `task-executor`, `redis`, `mongodb`, `qdrant`.
- Volumes: Mongo and Qdrant persistent volumes.
- Env config: `.env` loaded by services (DB URIs, Redis URL, LLM keys, CORS origins, JWT secret placeholder).
- Observability: expose Prometheus metrics from FastAPI and Celery (Flower optional later); structured JSON logs to stdout.

### Compose Notes
- Healthchecks: Redis `redis-cli ping`, Mongo `mongosh --eval "db.adminCommand('ping')"`, Qdrant `/readyz`, FastAPI `/health`.
- Resource hints: set memory limits for workers in compose file; pin CPU shares for Celery to avoid starving API.

## 12. Error Handling & Idempotency
- All tasks include `task_id` and `retry_count`; handlers are idempotent (safe re-run using `task_id` guards).
- Message handlers dedupe via `message_id` and persisted status transitions.
- Tool calls wrapped with circuit-breaker-like retry (limited) and timeouts.

### Observability Hooks
- Structured logs with correlation_id per request/task/message.
- Metrics: counters for task submissions/completions/failures; histograms for LLM latency; gauges for agent loop lag.
- Traces: optional OpenTelemetry exporter to console/OTLP.

## 13. Configuration Defaults (MVP)
- `MAX_CONCURRENT_TASKS_PER_USER=25` enforced in API before enqueue.
- `TASK_MAX_DURATION=300s`, `TASK_MAX_RETRIES=3`.
- Agent loop interval 1s; checkpoint every 30s or after significant state change.
- Redis channels, Mongo collections, Qdrant collections configurable via env.

### Config Loading
- Central `Settings` class (Pydantic) loaded from env; shared across services; override via `.env` for dev.

## 14. Security & Privacy (MVP stance)
- Transport: enable HTTPS/Traefik in production (not in dev compose).
- Auth: placeholder JWT; agent-to-agent via signed tokens (stub); future OAuth2 integration planned.
- Secrets: .env (dev); rotate manually; no plaintext logging of secrets.
- Cross-user messaging requires approval flag checked before delivery.

### Data Handling
- Do not log PII or secrets; mask emails/user identifiers where possible.
- Optional encryption at rest for Mongo (Atlas default) and TLS in transit for Redis/Mongo in prod.

## 15. Testing Strategy
- Unit: Pydantic models, DAG executor logic, tool registry validation.
- Integration: API flows (create agent → submit task → poll status); messaging pub/sub loop with Redis test container; Celery task execution with Redis.
- Load smoke: limited concurrency to validate `MAX_CONCURRENT_TASKS_PER_USER` enforcement.

### Test Data
- Factories for agents/tasks/messages with deterministic IDs for idempotency checks.
- Replay fixtures for LLM calls using recorded responses to keep tests fast and deterministic.

## 16. Migration Path Notes
- Swap Redis Pub/Sub with RabbitMQ by replacing messaging client; keep message schema stable.
- Move from process isolation to container isolation for tasks; keep Celery interface.
- Add cost controls and sharding later without changing high-level APIs.
