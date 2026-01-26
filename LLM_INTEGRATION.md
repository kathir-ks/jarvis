# LLM Provider Integration Guide

## Overview

The Jarvis platform uses an **interface-based architecture** for LLM provider integration, allowing seamless switching between different AI models (OpenAI, Gemini, Anthropic, etc.) without changing application code.

## Architecture Design

### 1. Provider Interface (`LLMProvider` Protocol)

All LLM providers implement the `LLMProvider` protocol defined in [jarvis/app/llm/base.py](jarvis/app/llm/base.py):

```python
class LLMProvider(Protocol):
    name: str
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult
```

**Key Benefits:**
- ✅ **Type-safe**: Static type checking with `Protocol`
- ✅ **Consistent API**: All providers return `LLMResult` with normalized structure
- ✅ **Async-native**: Non-blocking I/O for concurrent operations
- ✅ **Extensible**: Add new providers by implementing the protocol

### 2. Normalized Response (`LLMResult`)

Every provider returns a consistent response structure:

```python
@dataclass
class LLMResult:
    provider: str          # "openai", "gemini", etc.
    model: str            # "gpt-4o-mini", "gemini-1.5-flash"
    content: str          # Generated text
    finish_reason: str    # Why generation stopped
    usage: dict          # Token usage statistics
    raw_response_id: str # Original API response ID
    metadata: dict       # Provider-specific metadata
```

### 3. LLM Router (Provider Orchestration)

The `LLMRouter` class ([jarvis/app/llm/router.py](jarvis/app/llm/router.py)) handles:
- **Provider loading**: Automatically instantiates available providers based on API keys
- **Request routing**: Directs calls to the configured provider
- **Fallback support**: Can route to alternate providers (future enhancement)
- **Configuration**: Accepts per-request provider overrides

## Implemented Providers

### OpenAI Provider

**File**: [jarvis/app/llm/providers/openai_provider.py](jarvis/app/llm/providers/openai_provider.py)

**Supported Models**:
- `gpt-4o` - Latest GPT-4 Omni model
- `gpt-4o-mini` - Faster, cheaper GPT-4 variant
- `gpt-4-turbo` - Previous flagship model
- `gpt-3.5-turbo` - Fast, cost-effective model

**Configuration**:
```python
os.environ["JARVIS_OPENAI_API_KEY"] = "sk-..."
os.environ["JARVIS_DEFAULT_LLM_MODEL"] = "gpt-4o-mini"
```

**Features**:
- ✅ Full chat completions API
- ✅ Streaming support (future)
- ✅ Function calling (future)
- ✅ Token usage tracking

### Gemini Provider

**File**: [jarvis/app/llm/providers/gemini_provider.py](jarvis/app/llm/providers/gemini_provider.py)

**Supported Models**:
- `gemini-1.5-flash` - Fast, cost-effective (recommended)
- `gemini-1.5-pro` - Most capable Gemini model
- `gemini-1.0-pro` - Previous generation

**Configuration**:
```python
os.environ["JARVIS_GEMINI_API_KEY"] = "..."
os.environ["JARVIS_DEFAULT_GEMINI_MODEL"] = "gemini-1.5-flash"
```

**Features**:
- ✅ Full Gemini API integration
- ✅ Message format conversion (OpenAI → Gemini)
- ✅ System message handling
- ✅ Multi-turn conversations
- ✅ Token usage tracking

**Message Conversion Logic**:
```python
# OpenAI format → Gemini format
OpenAI: {"role": "system|user|assistant", "content": "..."}
Gemini: {"role": "user|model", "parts": ["..."]}

# System messages are prepended to the first user message
```

## Usage Examples

### Basic Usage with Default Provider

```python
from jarvis.app.llm.router import LLMRouter

router = LLMRouter()

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is an AI agent?"}
]

result = await router.call(messages)
print(result.content)  # AI-generated response
```

### Explicit Provider Selection

```python
# Force use of Gemini
result = await router.call(
    messages,
    config={
        "provider": "gemini",
        "model": "gemini-1.5-pro",
        "temperature": 0.7,
        "max_tokens": 1000
    }
)
```

### Using Providers Directly

```python
from jarvis.app.llm.providers import OpenAIProvider, GeminiProvider

# OpenAI
openai = OpenAIProvider(api_key="sk-...", default_model="gpt-4o-mini")
result = await openai.chat(messages, config={"temperature": 0.9})

# Gemini
gemini = GeminiProvider(api_key="...", default_model="gemini-1.5-flash")
result = await gemini.chat(messages, config={"max_tokens": 500})
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `JARVIS_DEFAULT_LLM_PROVIDER` | Primary provider | `openai` |
| `JARVIS_DEFAULT_LLM_MODEL` | OpenAI model | `gpt-4o-mini` |
| `JARVIS_DEFAULT_GEMINI_MODEL` | Gemini model | `gemini-1.5-flash` |
| `JARVIS_OPENAI_API_KEY` | OpenAI API key | `None` |
| `JARVIS_GEMINI_API_KEY` | Gemini API key | `None` |

### Settings Class

All configuration is centralized in [jarvis/app/core/settings.py](jarvis/app/core/settings.py):

```python
from jarvis.app.core.settings import get_settings

settings = get_settings()
print(settings.default_llm_provider)  # "openai"
print(settings.openai_api_key)        # "sk-..."
```

## Testing

### Running Tests

```bash
# Set API keys
export JARVIS_OPENAI_API_KEY="sk-..."
export JARVIS_GEMINI_API_KEY="..."

# Run test script
python test_llm_providers.py
```

### Test Coverage

The [test_llm_providers.py](test_llm_providers.py) script tests:
- ✅ OpenAI provider integration
- ✅ Gemini provider integration
- ✅ LLM router with automatic provider selection
- ✅ Explicit provider overrides
- ✅ Error handling

## Adding a New Provider

### Step 1: Implement the Provider

Create `jarvis/app/llm/providers/new_provider.py`:

```python
from ..base import LLMProvider, LLMResult

class NewProvider(LLMProvider):
    name = "newprovider"
    
    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key
        self.default_model = default_model
    
    async def chat(self, messages, config=None):
        config = config or {}
        model = config.get("model") or self.default_model
        
        # Call provider's API
        response = await call_provider_api(...)
        
        return LLMResult(
            provider=self.name,
            model=model,
            content=response.text,
            finish_reason=response.finish_reason,
            usage={"tokens": response.tokens},
            metadata={}
        )
```

### Step 2: Export the Provider

Update `jarvis/app/llm/providers/__init__.py`:

```python
from .new_provider import NewProvider

__all__ = ["OpenAIProvider", "GeminiProvider", "NewProvider"]
```

### Step 3: Register in Router

Update `jarvis/app/llm/router.py`:

```python
from .providers import OpenAIProvider, GeminiProvider, NewProvider

def _load_providers(self):
    providers = {}
    
    if self.settings.openai_api_key:
        providers["openai"] = OpenAIProvider(...)
    
    if self.settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(...)
    
    if self.settings.newprovider_api_key:
        providers["newprovider"] = NewProvider(...)
    
    return providers
```

### Step 4: Add Configuration

Update `jarvis/app/core/settings.py`:

```python
class Settings(BaseSettings):
    newprovider_api_key: str | None = Field(None)
    default_newprovider_model: str = Field("model-name")
```

## Architecture Benefits

### 1. **Loose Coupling**
Agents don't depend on specific LLM implementations—they only depend on the `LLMProvider` interface.

### 2. **Easy Testing**
Mock providers can be created for unit testing without API calls:

```python
class MockProvider(LLMProvider):
    name = "mock"
    
    async def chat(self, messages, config=None):
        return LLMResult(
            provider="mock",
            model="mock-model",
            content="Mocked response",
            finish_reason="stop"
        )
```

### 3. **Runtime Switching**
Change providers per-request without restarting:

```python
# Use OpenAI for complex reasoning
result1 = await router.call(messages, {"provider": "openai", "model": "gpt-4o"})

# Use Gemini for cost efficiency
result2 = await router.call(messages, {"provider": "gemini"})
```

### 4. **Cost Optimization**
Route to cheaper models for simple tasks, expensive models for complex ones:

```python
if task.complexity == "simple":
    config = {"provider": "gemini", "model": "gemini-1.5-flash"}
else:
    config = {"provider": "openai", "model": "gpt-4o"}

result = await router.call(messages, config)
```

### 5. **Vendor Independence**
No lock-in to a single provider—switch as pricing/capabilities evolve.

## Integration with Agent Runtime

The agent event loop uses the router seamlessly:

```python
# In agent_runner.py
class AgentRunner:
    def __init__(self, agent_id: str):
        self.llm_router = LLMRouter()
    
    async def _handle_message(self, message):
        messages = self.prompt_builder.build_agent_messages(...)
        llm_config = self._build_llm_config()  # From agent config
        
        # Router automatically selects provider
        result = await self.llm_router.call(messages, llm_config)
        
        # Use result.content for response
        await self._append_memory(role="assistant", content=result.content)
```

## Future Enhancements

### 1. Tool Calling Support
```python
class LLMProvider(Protocol):
    async def chat(self, messages, config, tools: list[Tool] | None = None):
        ...
```

### 2. Streaming Responses
```python
class LLMProvider(Protocol):
    async def stream_chat(self, messages, config) -> AsyncIterator[str]:
        ...
```

### 3. Automatic Fallback
```python
class LLMRouter:
    async def call_with_fallback(self, messages, config, fallback_providers: list[str]):
        for provider in [primary, *fallback_providers]:
            try:
                return await self.call(messages, {"provider": provider})
            except Exception:
                continue
```

### 4. Cost Tracking
```python
class LLMRouter:
    async def call(self, messages, config):
        result = await provider.chat(...)
        await self._track_cost(result.usage, result.model)
        return result
```

## Troubleshooting

### Provider Not Loaded

**Problem**: `ValueError: LLM provider 'gemini' is not configured`

**Solution**: Set the API key:
```bash
export JARVIS_GEMINI_API_KEY="your-key-here"
```

### Message Format Error

**Problem**: Provider-specific message format issues

**Solution**: The router normalizes messages automatically. If you're calling providers directly, ensure message format matches:
- OpenAI: `{"role": "user|assistant|system", "content": "..."}`
- Gemini: Converted internally from OpenAI format

### Rate Limiting

**Problem**: 429 errors from provider API

**Solution**: Add retry logic with exponential backoff (future enhancement) or use a different provider:
```python
try:
    result = await router.call(messages, {"provider": "openai"})
except RateLimitError:
    result = await router.call(messages, {"provider": "gemini"})
```

## References

- [OpenAI API Documentation](https://platform.openai.com/docs/api-reference)
- [Google Gemini API Documentation](https://ai.google.dev/docs)
- [Python Protocol Documentation](https://docs.python.org/3/library/typing.html#typing.Protocol)
