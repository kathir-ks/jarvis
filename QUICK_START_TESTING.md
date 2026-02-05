# Quick Start: Testing & Context Management

**TL;DR**: Run tests, verify improvements, no breaking changes.

---

## 1. Install New Dependency

```bash
pip install tiktoken==0.8.0
```

---

## 2. Run Gemini Workflow Tests

### Run All Tests
```bash
pytest tests/workflows/ -v --log-cli-level=INFO
```

### Run Individual Test Suites
```bash
# Basic calculations
pytest tests/workflows/test_gemini_basic_workflow.py -v

# Web research
pytest tests/workflows/test_gemini_research_workflow.py -v

# Code execution
pytest tests/workflows/test_gemini_code_workflow.py -v

# Memory & multi-turn
pytest tests/workflows/test_gemini_memory_workflow.py -v

# Complex multi-tool
pytest tests/workflows/test_gemini_complex_workflow.py -v
```

### Expected Results
- ✅ All 21 tests pass
- ✅ Average response time < 10s per workflow
- ✅ Tools called correctly (logged in output)
- ✅ Memory retrieval working (scores > 0.4)

---

## 3. Use Enhanced Context Management

### Option 1: Drop-In Replacement (Recommended)

Update `agent_runner.py` (line ~120):

```python
# OLD:
messages = self.prompt_builder.build_agent_messages(
    agent=self.agent,
    incoming_message=message,
    long_term_context=long_term_context,
)

# NEW:
messages = self.prompt_builder.build_agent_messages_with_budget(
    agent=self.agent,
    incoming_message=message,
    long_term_context=long_term_context,
    model=self.agent.config.model,
    tools=available_tools,  # Pass tool definitions
)
```

### Option 2: Gradual Migration

Keep old method for existing agents, use new method for new agents.

---

## 4. Verify Token Management

### Check Logs

Look for these log messages:

```
INFO - Building prompt with budget - Model: gemini-1.5-flash, Total window: 1000000, Available: 950000
INFO - Selected 8/50 memories using 1580/2000 tokens
INFO - Final prompt: 12450 tokens (+8900 tools = 21350 total)
```

### Monitor for Overflow

Should see **ZERO** of these warnings:
```
WARNING - Prompt too large (135000 tokens, limit 128000). Applying emergency truncation.
```

If you do see warnings:
1. Check if context is unusually large
2. Reduce `max_count` in memory selection (default: 10)
3. Adjust budget percentages in `token_counter.py`

---

## 5. Test Master Agent Analysis

### Quick Test Script

```python
from jarvis.app.runtime.task_analyzer import get_task_analyzer

analyzer = get_task_analyzer()

# Test simple task
simple = analyzer.analyze_task_complexity("What time is it?")
print(f"Simple task score: {simple['complexity_score']}")  # Should be 1-2

# Test complex task
complex = analyzer.analyze_task_complexity(
    "Search for Python tutorials, then write code to scrape the top result"
)
print(f"Complex task score: {complex['complexity_score']}")  # Should be 6-8
print(f"Should delegate: {complex['should_delegate']}")  # Should be True
print(f"Suggested agents: {complex['suggested_sub_agents']}")
# Should be ['web_research', 'code_execution']
```

---

## 6. Common Issues & Solutions

### Issue: `ModuleNotFoundError: No module named 'tiktoken'`
**Solution**: Run `pip install tiktoken==0.8.0`

### Issue: Tests fail with timeout
**Solution**: Increase timeout in test (default: 30s, increase to 60s for complex workflows)

### Issue: Token counter returns 0
**Solution**: Check text is not empty, verify model name is correct

### Issue: Memory selection returns empty list
**Solution**:
1. Check `agent.short_term_memory` has items
2. Verify `max_tokens` is not too restrictive (default: 2000)
3. Lower similarity threshold

---

## 7. Performance Monitoring

### Metrics to Track

```python
from jarvis.app.llm.token_counter import get_token_counter

counter = get_token_counter()

# Before LLM call
start_tokens = counter.count_messages_tokens(messages, model)
print(f"Input tokens: {start_tokens}")

# After LLM call
total_used = start_tokens + response_tokens
window = counter.get_context_window(model)
utilization = (total_used / window) * 100
print(f"Context utilization: {utilization:.1f}%")
```

**Target Metrics**:
- Context utilization: 85-95% (optimal)
- Memory selection: 8-12 items per prompt
- Token waste: < 5% (unused budget)

---

## 8. Rollback Plan

If issues occur, rollback is simple:

### Revert Prompt Builder
```python
# In agent_runner.py, change back to:
messages = self.prompt_builder.build_agent_messages(
    agent=self.agent,
    incoming_message=message,
    long_term_context=long_term_context,
)
```

### Uninstall tiktoken (optional)
```bash
pip uninstall tiktoken
```

**Note**: Old method still works, new features are additive only.

---

## 9. Configuration Tuning

### Adjust Memory Selection

In `agent_runner.py`:

```python
# Conservative (use less tokens)
selected_memories = self.memory_selector.select_short_term_memories(
    memories=agent.short_term_memory,
    query=user_content,
    max_count=5,        # ← Reduce from 10
    max_tokens=1000,    # ← Reduce from 2000
)

# Aggressive (use more context)
selected_memories = self.memory_selector.select_short_term_memories(
    memories=agent.short_term_memory,
    query=user_content,
    max_count=15,       # ← Increase from 10
    max_tokens=3000,    # ← Increase from 2000
)
```

### Adjust Time Weighting

In vector memory search:

```python
# Favor recent memories more
context = await vector_memory.get_recent_context(
    user_id=user_id,
    agent_id=agent_id,
    query=query,
    recency_weight=0.5,  # ← Increase from 0.3
)

# Favor similarity more
context = await vector_memory.get_recent_context(
    user_id=user_id,
    agent_id=agent_id,
    query=query,
    recency_weight=0.1,  # ← Decrease from 0.3
)
```

### Adjust Budget Allocation

In `jarvis/app/llm/token_counter.py` (line ~220):

```python
# Example: Give more budget to short-term memory
return {
    "total_window": total_window,
    "available": available,
    "system": int(available * 0.15),     # ← Reduced from 0.20
    "tools": int(available * 0.30),      # Same
    "short_term": int(available * 0.25), # ← Increased from 0.20
    "long_term": int(available * 0.15),  # Same
    "current": int(available * 0.10),    # Same
    "reserve": int(available * 0.05),    # Same
}
```

---

## 10. Next Steps After Testing

### Week 1: Validation
- ✅ Run all 21 workflow tests
- ✅ Verify 0 context overflow errors
- ✅ Collect token usage metrics
- ✅ Confirm response quality maintained/improved

### Week 2: Integration
- ✅ Update `agent_runner.py` to use budget-aware builder
- ✅ Add token usage logging
- ✅ Monitor production metrics

### Week 3: Optimization
- ✅ Tune memory selection parameters
- ✅ Adjust budget percentages if needed
- ✅ Profile long-running conversations

### Week 4: Documentation
- ✅ Update `CURRENT_STATE.md` with completion status
- ✅ Create performance report
- ✅ Plan Phase 4 multi-agent features

---

## 11. Support & Debugging

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("jarvis.app.llm.token_counter")
logger.setLevel(logging.DEBUG)
```

### Inspect Token Budgets

```python
from jarvis.app.llm.token_counter import get_token_counter

counter = get_token_counter()
budget = counter.get_token_budget_breakdown("gemini-1.5-flash")

print(f"Total window: {budget['total_window']:,}")
print(f"System budget: {budget['system']:,}")
print(f"Short-term budget: {budget['short_term']:,}")
```

### Check Memory Selection

```python
from jarvis.app.runtime.memory_selector import get_memory_selector

selector = get_memory_selector()

# Enable logging
import logging
logging.getLogger("jarvis.app.runtime.memory_selector").setLevel(logging.DEBUG)

# Run selection and check logs
selected = selector.select_short_term_memories(...)
```

---

## 12. FAQ

**Q: Will this break existing agents?**
A: No. Old method `build_agent_messages()` still works. New method is opt-in.

**Q: Do I need to update my database?**
A: No. Changes are runtime-only, no schema changes.

**Q: What if tiktoken install fails?**
A: Token counter falls back to approximation (4 chars/token). Accuracy slightly reduced but still works.

**Q: Can I use this with Anthropic/Claude models?**
A: Yes. Token counter supports Claude (3.5 chars/token approximation).

**Q: How do I know if budget management is working?**
A: Check logs for "Building prompt with budget" and "Final prompt: X tokens". Should see no overflow warnings.

**Q: What's the performance impact?**
A: Minimal. Token counting adds ~10-20ms. Memory selection adds ~5-10ms. Total overhead < 50ms.

---

**Quick Start Complete!** 🚀

For detailed information, see `IMPLEMENTATION_SUMMARY.md`.
For architecture details, see `CLAUDE.md`.
For current status, see `CURRENT_STATE.md`.
