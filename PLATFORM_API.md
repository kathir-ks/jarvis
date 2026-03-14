# Communication Platform API Reference

> **Base URL**: `http://localhost:9000/api/v1`
>
> **Start the platform**: `python run_platform.py`

The Communication Platform is a standalone FastAPI service that provides multi-agent messaging, discovery, and health monitoring. It runs with zero external infrastructure — all state is held in-memory.

---

## Endpoints

### Agent Registration

#### `POST /api/v1/agents/register`

Register an agent in the platform directory.

**Request Body**:
```json
{
  "agent_id": "agent-kathir-abc123",
  "user_id": "kathir",
  "agent_type": "master",
  "capabilities": ["general_assistance", "web_research"],
  "metadata": {
    "model": "gemma-3-4b-it",
    "provider": "gemini"
  }
}
```

**Response** (`200 OK`):
```json
{
  "ok": true,
  "agent_id": "agent-kathir-abc123",
  "message": "registered"
}
```

---

#### `POST /api/v1/agents/unregister`

Remove an agent from the directory.

**Request Body**:
```json
{
  "agent_id": "agent-kathir-abc123"
}
```

**Response** (`200 OK`):
```json
{
  "ok": true,
  "agent_id": "agent-kathir-abc123",
  "message": "unregistered"
}
```

**Error** (`404 Not Found`): Agent not in directory.

---

### Messaging

#### `POST /api/v1/messages/send`

Route a message from one agent to another.

**Request Body**:
```json
{
  "from_id": "agent-kathir-abc123",
  "to_id": "agent-aswin-def456",
  "message_type": "peer_message",
  "content": {
    "text": "What deployment strategy do you recommend?"
  },
  "ttl_seconds": 300
}
```

**Response** (`200 OK`):
```json
{
  "ok": true,
  "message_id": "agent:agent-aswin-def456:inbox-a1b2c3d4e5f6"
}
```

**Supported `message_type` values**:
- `peer_message` — Standard agent-to-agent message
- `delegation_request` — Master→sub-agent delegation
- `delegation_result` — Sub-agent→master result
- `request` — Request expecting a correlated response
- `response` — Correlated response to a request

---

#### `POST /api/v1/messages/broadcast`

Broadcast a message to all agents, optionally scoped to a topic.

**Request Body**:
```json
{
  "from_id": "agent-akilesh-ghi789",
  "content": {
    "text": "System update: switching to Gemma 3 4B for all agents."
  },
  "topic": ""
}
```

**Response** (`200 OK`):
```json
{
  "ok": true,
  "message_id": "broadcast:all-a1b2c3d4e5f6"
}
```

Set `topic` to a non-empty string to publish to a specific topic channel (e.g., `"topic": "deployments"`).

---

### Health Monitoring

#### `POST /api/v1/heartbeat`

Process a heartbeat from an agent. Updates the agent's health status and last-seen timestamp in the directory.

**Request Body**:
```json
{
  "agent_id": "agent-kathir-abc123",
  "status": "alive",
  "active_tasks": 2,
  "metadata": {
    "cpu_percent": 45.2
  }
}
```

**Response** (`200 OK`):
```json
{
  "ok": true,
  "acknowledged": true
}
```

`acknowledged: false` means the agent is not registered in the directory.

**Supported `status` values**:
- `alive` — Agent is healthy
- `busy` — Agent is under heavy load
- `degraded` — Agent is experiencing issues

---

### Directory

#### `GET /api/v1/directory/agents`

List registered agents with optional filtering.

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | string | Filter by owning user |
| `capability` | string | Filter by capability |

**Examples**:
```
GET /api/v1/directory/agents                        # All agents
GET /api/v1/directory/agents?user_id=kathir          # kathir's agents
GET /api/v1/directory/agents?capability=web_research  # Agents with web_research
GET /api/v1/directory/agents?user_id=kathir&capability=general_assistance
```

**Response** (`200 OK`):
```json
{
  "agents": [
    {
      "agent_id": "agent-kathir-abc123",
      "user_id": "kathir",
      "agent_type": "master",
      "capabilities": ["general_assistance", "web_research"],
      "health": "healthy",
      "active_tasks": 0,
      "metadata": {
        "model": "gemma-3-4b-it",
        "provider": "gemini"
      }
    }
  ],
  "total": 1
}
```

---

#### `GET /api/v1/health`

Platform health check.

**Response** (`200 OK`):
```json
{
  "status": "ok",
  "total_agents": 3,
  "healthy": 3,
  "busy": 0,
  "degraded": 0
}
```

---

## Usage Patterns

### Single-Process Demo (InMemoryBroker)

All agents share an `InMemoryMessageBroker` in one Python process. Messages are delivered synchronously — no network I/O.

```bash
python run_multi_agent_demo.py --provider gemini --model gemma-3-4b-it
```

### Standalone Platform Service

The platform runs as a FastAPI server. Agents in separate processes will connect via HTTP (once `HttpPlatformBroker` is implemented).

```bash
# Terminal 1: Start platform
python run_platform.py --port 9000

# Terminal 2: Start agent (currently standalone, HTTP broker planned)
python run_agent.py --user kathir --provider gemini --model gemma-3-4b-it
```

### Programmatic Usage

```python
from jarvis.app.platform.app import create_platform_app
from jarvis.app.lite.memory_broker import InMemoryMessageBroker
from jarvis.app.runtime.agent_directory import AgentDirectory

# Create platform with shared components
broker = InMemoryMessageBroker()
directory = AgentDirectory()
app = create_platform_app(broker=broker, directory=directory)

# Use broker and directory in your agent runners too
```

---

## Data Models

### AgentInfo
```python
{
    "agent_id": str,       # Unique agent identifier
    "user_id": str,        # Owning user (e.g., "kathir")
    "agent_type": str,     # "master" or "sub_agent"
    "capabilities": [str], # e.g., ["general_assistance", "web_research"]
    "health": str,         # "healthy", "busy", "degraded"
    "active_tasks": int,   # Current active task count
    "metadata": dict       # Arbitrary metadata (model, provider, etc.)
}
```

### AgentMessage (internal envelope)
```python
{
    "message_id": str,     # Auto-generated unique ID
    "message_type": str,   # See supported types above
    "sender_id": str,      # Sending agent ID
    "recipient_id": str,   # Target agent ID (empty for broadcasts)
    "content": dict,       # Message payload
    "priority": str,       # "low", "normal", "high", "urgent"
    "timestamp": str,      # ISO-8601 send timestamp
    "ttl_seconds": int,    # Time-to-live (0 = no expiry)
    "correlation_id": str, # Links request→response pairs
    "topic": str           # Topic name for topic-based messages
}
```

---

**Last Updated**: March 14, 2026
