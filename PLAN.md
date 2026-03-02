# Plan: Master-SubAgent Workflow & Context Management Improvements

## Problem Analysis

After reviewing the codebase, the master-subagent delegation workflow (Phase 4) has solid
foundations but has several concrete gaps in **context management** that limit its effectiveness:

1. **No context flows from master to sub-agents** - Delegation messages pass `"context": {}` (empty).
   Sub-agents start with a clean slate, unaware of the master's conversation history, user
   preferences, or the broader task scope. (`master_agent.py:445`)

2. **Sub-agent delegation skips long-term memory** - `_handle_delegation_request()` builds
   prompts without retrieving Qdrant context, unlike normal message handling. (`agent_runner.py:414`)

3. **No inter-subtask context sharing** - When subtasks are sequential (research -> code),
   the second sub-agent doesn't receive results from the first. All subtasks are independent.

4. **Subtask description generation is purely mechanical** - Uses string prefix + truncation
   rather than understanding what part of the task is relevant. (`master_agent.py:264-303`)

5. **Delegation results aren't stored in memory** - After aggregation, results disappear.
   Future tasks can't reference past delegation outcomes.

6. **Token-budget-aware prompt building isn't used for delegations** - The runner uses
   `build_agent_messages()` everywhere, not `build_agent_messages_with_budget()`.

7. **Capability registry is in-memory only** - Lost on restart, no MongoDB persistence.

---

## Implementation Steps

### Step 1: Create `DelegationContext` model and `DelegationContextManager`

**New file:** `jarvis/app/runtime/delegation_context.py`

Create a dedicated context management layer for delegation workflows:

```python
class DelegationContext(BaseModel):
    """Context package passed from master to sub-agent."""
    parent_task_description: str          # The full original task
    subtask_description: str              # The focused subtask
    parent_short_term_summary: str        # Summary of master's recent conversation
    parent_session_context: dict          # Relevant session state from master
    sibling_results: list[dict]           # Results from previously completed subtasks
    user_preferences: dict                # User-specific preferences/style
    delegation_chain_depth: int           # How deep in the delegation hierarchy

class DelegationContextManager:
    """Manages context packaging, propagation, and storage for delegations."""

    def build_context_for_sub_agent(
        self, master_agent, task, subtask, prior_results, ...
    ) -> DelegationContext:
        """Package relevant master context for a sub-agent."""

    def build_sequential_context(
        self, prior_results, current_subtask, ...
    ) -> dict:
        """Build context for sequential subtasks, including prior results."""

    async def store_delegation_result(
        self, vector_memory, agent_id, user_id, task, aggregated_result
    ) -> None:
        """Store completed delegation results in long-term memory."""
```

**Why:** Centralizes context packaging logic instead of scattering it across master_agent.py
and agent_runner.py. Makes context propagation testable and configurable.

---

### Step 2: Wire context propagation into `MasterAgentOrchestrator`

**File:** `jarvis/app/runtime/master_agent.py`

Changes:
- Import and use `DelegationContextManager`
- In `delegate_to_sub_agent()`: replace empty `"context": {}` with a populated
  `DelegationContext` built from the master's state
- In `orchestrate_delegation()`: for sequential subtasks, pass results from completed
  subtasks to subsequent ones
- In `orchestrate_delegation()` after aggregation: store results in vector memory
- Accept the master's `Agent` object to access short-term memory and session context

```python
# In delegate_to_sub_agent():
delegation_message = {
    ...
    "context": self.context_manager.build_context_for_sub_agent(
        master_agent=self._agent,
        task=original_task,
        subtask=subtask,
        prior_results=prior_results,
    ).model_dump(),
    ...
}
```

---

### Step 3: Sub-agent uses delegation context during execution

**File:** `jarvis/app/runtime/agent_runner.py`

Changes to `_handle_delegation_request()`:
- Extract the `DelegationContext` from the delegation payload
- Retrieve long-term memory from Qdrant (currently skipped)
- Pass both delegation context and long-term memory to prompt builder
- Use `build_agent_messages_with_budget()` instead of `build_agent_messages()`

```python
async def _handle_delegation_request(self, payload):
    context = payload.get("context", {})

    # Retrieve long-term memory (currently missing)
    long_term_context = None
    if self.vector_memory:
        long_term_context = await self.vector_memory.get_recent_context(...)

    # Build prompt with delegation context + long-term memory
    llm_messages = self.prompt_builder.build_delegation_messages(
        agent=self.agent,
        delegation_context=context,
        long_term_context=long_term_context,
    )
```

---

### Step 4: Add delegation-aware prompt building to `PromptBuilder`

**File:** `jarvis/app/llm/prompt_builder.py`

Add a new method for building delegation-specific prompts:

```python
def build_delegation_messages(
    self,
    agent: Agent,
    delegation_context: dict,
    long_term_context: dict | None = None,
) -> list[dict[str, str]]:
    """Build messages for sub-agent delegation execution.

    Includes:
    - Sub-agent system prompt (role-aware)
    - Parent task context (overall goal)
    - Results from sibling subtasks (if sequential)
    - Long-term memory context
    - The focused subtask instruction
    """
```

The system prompt for delegated work should differ from normal conversation:
- Make the sub-agent aware it's executing a subtask for a larger goal
- Include the overall task description for context
- Include sibling results so the sub-agent can build on prior work
- Keep the subtask instruction focused

---

### Step 5: Persist capability registry to MongoDB

**Files:**
- `jarvis/app/runtime/agent_capabilities.py` - Add async persistence methods
- `jarvis/app/db/repositories.py` - Add `CapabilityRepository`

Changes:
- Add a `CapabilityRepository` with methods: `save_capabilities()`, `load_capabilities()`,
  `delete_agent_capabilities()`
- Make `AgentCapabilitiesRegistry` load from MongoDB on initialization
- Write-through: persist to MongoDB when capabilities change
- Keep in-memory cache for fast lookups

---

### Step 6: Store delegation results in long-term memory

**Files:**
- `jarvis/app/runtime/master_agent.py`
- `jarvis/app/runtime/delegation_context.py`

After `aggregate_results()` in `orchestrate_delegation()`:
- Store the full delegation workflow (task, subtasks, results) in vector memory
  as a `knowledge` entry with type `delegation_result`
- Future tasks can discover past delegation outcomes via semantic search

---

### Step 7: Tests

**Files:**
- `tests/workflows/test_delegation_context.py` (new)
- `tests/workflows/test_master_delegation.py` (extend existing)

Test cases:
- `DelegationContext` model creation and serialization
- `DelegationContextManager.build_context_for_sub_agent()` with various agent states
- Sequential context chaining (prior results passed to next subtask)
- `build_delegation_messages()` prompt structure and content
- Delegation result storage in vector memory
- Capability repository persistence (save/load/delete)
- End-to-end: master delegates with context, sub-agent receives and uses it

---

## Files Modified/Created

| File | Action | Description |
|------|--------|-------------|
| `jarvis/app/runtime/delegation_context.py` | **Create** | DelegationContext model + DelegationContextManager |
| `jarvis/app/runtime/master_agent.py` | **Modify** | Wire context manager, pass context in delegations, store results |
| `jarvis/app/runtime/agent_runner.py` | **Modify** | Use delegation context in sub-agent execution, add Qdrant lookup |
| `jarvis/app/llm/prompt_builder.py` | **Modify** | Add `build_delegation_messages()` method |
| `jarvis/app/runtime/agent_capabilities.py` | **Modify** | Add async persistence via repository |
| `jarvis/app/db/repositories.py` | **Modify** | Add `CapabilityRepository` |
| `tests/workflows/test_delegation_context.py` | **Create** | Tests for context management |
| `tests/workflows/test_master_delegation.py` | **Modify** | Extend with context-aware tests |

## Execution Order

1. Step 1 (DelegationContext model + manager) - foundation, no dependencies
2. Step 4 (Prompt builder delegation method) - depends on Step 1 model
3. Step 2 (Wire into master_agent.py) - depends on Steps 1, 4
4. Step 3 (Sub-agent uses context) - depends on Steps 1, 4
5. Step 5 (Capability persistence) - independent, can be done in parallel
6. Step 6 (Store results in memory) - depends on Steps 2, 3
7. Step 7 (Tests) - after each step, but comprehensive suite at end
