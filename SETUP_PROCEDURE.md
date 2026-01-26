# Jarvis Agent Setup Procedure

## Current State
- Core runtime, repositories, services: ✅ Complete
- LLM providers (OpenAI/Gemini): ✅ Complete
- Tool calling & MCP: ✅ Complete (Phase 3 Done)
- Agent-to-agent communication: ❌ Not implemented (Phase 4 Pending)

---

## Phase 1: Get Basic Agent Running

### 1.1 Fix Vector Memory Service
- Complete `store_interaction()` method
- Implement `search_similar()` for retrieval
- Add memory consolidation (short→long-term)

### 1.2 Verify LLM Integration
- Test OpenAI/Gemini provider connectivity
- Ensure prompt builder works with memory context

### 1.3 Test Agent Lifecycle
- Create agent → Start → Send message → Verify response
- Check MongoDB persistence and checkpointing

---

## Phase 2: Tooling Integration

### 2.1 Define Tool Schema
- Create OpenAI-compatible function calling schema
- Define tool interface with input/output types

### 2.2 Implement Core Tools
- `web_search`: Search the web (SerpAPI/DuckDuckGo)
- `read_url`: Fetch and parse webpage content
- `execute_code`: Run Python code safely

### 2.3 Integrate Tools with LLM
- Update LLM router to support tool calling
- Parse tool calls from LLM response
- Execute tools and return results to LLM

---

## Phase 3: MCP Setup

### 3.1 Create MCP Server
- Implement MCP protocol handler
- Expose tools via MCP interface
- Handle tool invocation requests

### 3.2 Register MCP Tools
- Define tool manifests (name, description, schema)
- Register tools with MCP server

### 3.3 Connect Agent to MCP
- Agent discovers available tools via MCP
- Agent invokes tools through MCP protocol

---

## Phase 4: Agent-to-Agent Communication

### 4.1 Agent Discovery
- Register agents in shared registry
- Query available agents by capability

### 4.2 Message Protocol
- Define inter-agent message format
- Implement routing between agents

### 4.3 Collaboration Patterns
- Master delegates tasks to sub-agents
- Sub-agents report results back
- Parallel task distribution

---

## Execution Order
1. Phase 1.1 → 1.2 → 1.3 (sequential)
2. Phase 2.1 → 2.2 → 2.3 (sequential)
3. Phase 3.1 → 3.2 → 3.3 (sequential)
4. Phase 4.1 → 4.2 → 4.3 (sequential)
