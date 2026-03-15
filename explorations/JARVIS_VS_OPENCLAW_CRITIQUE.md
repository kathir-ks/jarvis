# Jarvis vs OpenClaw — Design Critique & Comparison

> **Date**: March 15, 2026
> **Purpose**: Critical analysis of both platforms' architecture, capabilities, and gaps to inform Jarvis's roadmap.

---

## Part 1: Jarvis Agent Platform — Critique

### Strengths

**1. Clean Protocol Abstractions**
- `MessageBrokerProtocol` using `@runtime_checkable` is elegant — allows swapping Redis for in-memory with zero code changes
- `LiteAgentRunner` uses constructor injection throughout, making it testable and infrastructure-agnostic

**2. DAG-based Task Execution**
- Topological sort + concurrent execution (up to 5 parallel tasks) is a genuine differentiator
- Dependency resolution with cascading failure cancellation is well-designed
- This is something OpenClaw completely lacks

**3. MCP Protocol Support**
- Both server and client implementations — agents can expose tools AND discover tools from remote MCP servers
- Forward-looking design choice that aligns with the emerging standard

**4. Multi-Provider LLM Routing**
- Gemini key rotation with quota detection is sophisticated
- Pydantic-based tool schemas that normalize across providers

**5. Multi-User Architecture**
- `user_id`-scoped agent directory, per-user runners, communication platform REST API
- Clear separation between agent identity and user identity

### Weaknesses

**1. No Real-World I/O Channels**
- Zero messaging integrations (no WhatsApp, Telegram, Slack, Discord)
- Only interface is programmatic API or REPL — users can't actually *use* this as an assistant
- The "communication platform" is agent-to-agent only, not user-facing

**2. Hidden Global State / Incomplete DI**
- `AgentRunner` (the full one) directly instantiates repositories, broker, router — violating the IoC pattern that `LiteAgentRunner` gets right
- Singletons: `get_tool_registry()`, `get_vector_memory_service()`, `get_agent_directory()` are called in constructors, creating untestable hidden dependencies

**3. DAG Executor Has Critical Bugs**
- **No cycle detection** — circular dependencies cause infinite deadlock
- **No per-task timeout** — `max_duration` field exists on Task but is never enforced
- **Ignores priority** — `task.priority` field is defined but ready queue is FIFO
- These aren't edge cases; they're correctness issues

**4. Memory System is Half-Built**
- No automatic short-term → long-term promotion
- Short-term buffer grows unbounded (no LRU eviction)
- Vector search scores are computed but never used for ranking
- Memory only stored during message handling, not during task execution

**5. Error Recovery is Simplistic**
- Fixed 5-second sleep on ANY error — no exponential backoff, no error classification
- No provider failover chain — if OpenAI quota is hit, no fallback to Gemini
- No circuit breaker on LLM calls (circuit breaker exists for agent-to-agent, not LLM)

**6. Lite Mode is Untested**
- Zero unit tests for `InMemoryMessageBroker` or `InMemoryAgentRepository`
- The only validation is `run_multi_agent_demo.py` — a demo, not a test
- Async wrappers on synchronous dict operations are misleading

**7. Tool System is Minimal**
- Only 5 tools: `execute_code`, `get_time`, `calculator`, `web_search`, `read_url`
- No file I/O, no shell execution, no process management
- No tool access policies or sandboxing
- No tool feedback loop — results aren't evaluated for quality

---

## Part 2: OpenClaw — Critique

### Strengths

**1. Production-Grade Messaging Integration**
- 10+ real channels: WhatsApp (Baileys), Telegram (grammY), Slack, Discord, Signal, iMessage, Google Chat, Teams, Matrix
- This is the single biggest practical advantage — users can actually talk to their agent

**2. Hybrid Memory Search**
- SQLite-vec with BM25 + semantic vector search combined
- Embedding cache to avoid recomputation
- Session compaction (old turns → memory embeddings + LLM summary)
- Practical, efficient, and local-first

**3. Tool Policy & Sandboxing**
- Fine-grained access control: global/workspace/per-model/per-provider rules
- Docker sandbox for untrusted code execution
- PTY-based shell with approval system for sensitive commands
- This is the mature approach to tool safety

**4. Robust Error Handling**
- `FailoverError` with typed reason codes (`auth | rate-limit | context-overflow | timeout`)
- Auth profile rotation with cooldown tracking
- LLM fallback chains configurable per-agent

**5. Session & Context Management**
- JSONL transcript persistence per session
- Configurable `maxTurns` and `maxTokens` for context window guardrails
- Session compaction prevents unbounded growth
- Session key routing: `channel/peerKind/peerId:accountId`

**6. Plugin Architecture**
- Full SDK with hooks (auth, messaging, tools, config validation)
- Runtime plugin discovery and loading
- Extension packages as npm dependencies

**7. Testing Discipline**
- 70% coverage threshold enforced
- Unit, E2E, live, and Docker test matrix
- Colocated test files (`*.test.ts`) for discoverability

### Weaknesses

**1. No DAG/Task Orchestration**
- Tool calls are sequential within a turn — no parallelism
- No task dependency graph, no concurrent subtask execution
- Complex workflows require agents to manually coordinate via `sessions_send`
- For multi-step research/planning tasks, this is a significant limitation

**2. No MCP Support**
- Uses proprietary tool registration — not compatible with the emerging MCP standard
- Plugin SDK partially fills this gap but isn't interoperable with external MCP servers
- As MCP gains adoption, this becomes a growing disadvantage

**3. Single-Process Architecture**
- One gateway per host, no clustering or horizontal scaling
- State (pairing tokens, sessions) is not replicated
- Memory indexing is per-agent, no cross-agent search

**4. Configuration Complexity**
- 1000+ line Zod schema with legacy migration paths
- Massive surface area for misconfiguration
- New users face a steep learning curve

**5. No Multi-User Support (by design)**
- Built as a personal assistant — one user per instance
- No concept of `user_id`-scoped agents or directories
- Multi-tenant deployment requires running separate instances

**6. No Agent-to-Agent Protocol**
- `sessions_send` is a simple message queue, not a protocol
- No correlation IDs, no request-response patterns, no broadcast topics
- No agent discovery (agents must know session keys)

---

## Part 3: Head-to-Head Comparison

| Dimension | Jarvis | OpenClaw | Winner |
|-----------|--------|----------|--------|
| **Real-world usability** | REPL/API only | 10+ messaging channels | OpenClaw |
| **Task orchestration** | DAG executor, parallel tasks, dependencies | Sequential, manual coordination | Jarvis |
| **MCP protocol** | Full server + client | None | Jarvis |
| **Memory system** | Basic (incomplete consolidation) | Hybrid BM25+vector, compaction | OpenClaw |
| **Tool safety** | None (no sandboxing, no policies) | Docker sandbox + policy engine | OpenClaw |
| **Tool breadth** | 5 tools | 20+ (file I/O, shell, process, memory) | OpenClaw |
| **Multi-user** | User-scoped directory, platform API | Single-user per instance | Jarvis |
| **Agent communication** | Typed envelopes, broadcast, circuit breaker | Simple `sessions_send` | Jarvis |
| **LLM failover** | None (single provider, no fallback) | Fallback chains with reason codes | OpenClaw |
| **Error handling** | Fixed 5s sleep | Typed errors, profile rotation, cooldowns | OpenClaw |
| **Testing** | Moderate (lite mode untested) | 70% enforced, multi-tier matrix | OpenClaw |
| **Config/Setup** | Simple `.env` | 1000+ line schema (complex) | Jarvis (simpler) |
| **Plugin system** | None | Full SDK with hooks | OpenClaw |
| **Streaming** | None visible | Block streaming, soft chunking | OpenClaw |
| **Architecture vision** | Multi-agent orchestration platform | Personal AI assistant | Different goals |

---

## Part 4: What Jarvis Should Learn from OpenClaw

1. **Real channels matter** — Without WhatsApp/Telegram/Slack integration, Jarvis is a demo, not a product. OpenClaw's channel dock pattern with normalized routing is worth studying.

2. **Hybrid memory search** — BM25 + vector is strictly better than vector-only. SQLite-vec is simpler and more portable than Qdrant for local deployments.

3. **Tool policies and sandboxing** — Jarvis lets agents execute arbitrary code with zero guardrails. OpenClaw's policy engine (global/workspace/model scopes) + Docker sandbox is the minimum for safe operation.

4. **LLM failover chains** — Provider-level fallback with typed error reasons (`rate-limit`, `context-overflow`, `auth`) is essential for reliability. Jarvis's "try once and fail" approach is fragile.

5. **Session compaction** — OpenClaw's approach to pruning old turns and summarizing them into embeddings prevents unbounded context growth. Jarvis's short-term memory has no eviction strategy.

6. **Testing discipline** — 70% coverage threshold, live tests, Docker E2E is a higher bar than Jarvis's current coverage.

---

## Part 5: What OpenClaw Should Learn from Jarvis

1. **DAG task execution** — For complex multi-step workflows (research → analyze → plan → execute), Jarvis's topological sort + parallel execution is genuinely useful. OpenClaw's manual agent coordination doesn't scale.

2. **MCP protocol** — The emerging standard for tool discovery/sharing. Jarvis is ahead here.

3. **Multi-user support** — Jarvis's `user_id`-scoped directories and communication platform enable multi-tenant deployments that OpenClaw can't do.

4. **Agent-to-agent protocol** — Typed message envelopes, circuit breakers, heartbeat-based health monitoring, and load-balanced agent selection are more mature than `sessions_send`.

5. **Lite mode abstraction** — The ability to swap infrastructure (Redis → InMemory, MongoDB → dict) via protocol abstractions is an elegant testing/dev story.

---

## Part 6: Recommended Next Steps for Jarvis

Prioritized by impact:

1. **Fix DAG executor bugs** (cycle detection, timeout enforcement, priority ordering) — these are correctness issues in Jarvis's strongest feature
2. **Add LLM failover chains** — low effort, high reliability impact
3. **Implement tool sandboxing** — at minimum, a policy layer; ideally Docker isolation
4. **Build hybrid memory** — add BM25 keyword search alongside vector search, implement compaction
5. **Add at least one real channel** (Telegram is easiest) — transforms Jarvis from demo to usable
6. **Test lite mode** — the in-memory implementations are load-bearing and completely untested
