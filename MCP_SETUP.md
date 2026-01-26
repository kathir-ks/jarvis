## Model Context Protocol (MCP) - Implementation Guide

**Status:** ✅ Complete (Phases 3.1 & 3.2)

## Overview

The Jarvis MCP server exposes all registered tools via the standardized Model Context Protocol, allowing external applications, AI assistants, and agents to discover and invoke tools in a vendor-neutral way.

## Architecture

```
┌─────────────────┐
│  External       │
│  MCP Client     │
└────────┬────────┘
         │ HTTP/JSON-RPC 2.0
         ▼
┌─────────────────────────┐
│   FastAPI MCP Router    │  /mcp endpoint
│   (routes/mcp.py)       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   MCP Server            │
│   (mcp/server.py)       │
│                         │
│  - Protocol Handler     │
│  - Tool Discovery       │
│  - Tool Invocation      │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   Tool Registry         │
│   (llm/tool_registry)   │
│                         │
│  - execute_code         │
│  - calculator           │
│  - get_time             │
│  - web_search           │
│  - read_url             │
└─────────────────────────┘
```

## MCP Protocol Methods

### 1. Initialize
**Method:** `initialize`

Initialize connection with the MCP server and get server capabilities.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": {
      "name": "my-client",
      "version": "1.0.0"
    }
  },
  "id": 1
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
      "name": "jarvis-mcp-server",
      "version": "0.1.0"
    },
    "capabilities": {
      "tools": {
        "listChanged": false
      }
    }
  }
}
```

### 2. List Tools
**Method:** `tools/list`

Get all available tools with their schemas.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 2
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "calculator",
        "description": "Evaluate mathematical expressions safely...",
        "inputSchema": {
          "type": "object",
          "properties": {
            "expression": {
              "type": "string",
              "description": "Mathematical expression to evaluate"
            }
          },
          "required": ["expression"]
        }
      }
      // ... more tools
    ]
  }
}
```

### 3. Call Tool
**Method:** `tools/call`

Execute a tool with given arguments.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "calculator",
    "arguments": {
      "expression": "sqrt(144) + 10"
    }
  },
  "id": 3
}
```

**Response (Success):**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"success\": true, \"expression\": \"sqrt(144) + 10\", \"result\": 22.0}"
      }
    ],
    "isError": false
  }
}
```

**Response (Error):**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Error: Tool 'nonexistent' not registered"
      }
    ],
    "isError": true
  }
}
```

### 4. Ping
**Method:** `ping`

Health check endpoint.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "ping",
  "id": 4
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "status": "ok",
    "timestamp": ""
  }
}
```

## HTTP Endpoints

### POST /mcp
Main MCP endpoint for JSON-RPC requests.

**Content-Type:** `application/json`

### GET /mcp/manifest
Get the complete tool manifest in a single request.

**Response:**
```json
{
  "server": {
    "name": "jarvis-mcp-server",
    "version": "0.1.0"
  },
  "tools": [
    {
      "name": "calculator",
      "description": "...",
      "category": "data",
      "parameters": [...]
    }
  ]
}
```

### GET /mcp/health
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "service": "mcp-server"
}
```

## Registered Tools

All tools from the Tool Registry are automatically exposed via MCP:

1. **execute_code** (code)
   - Execute Python code safely in a sandbox
   - Parameters: code (string), timeout (number)

2. **calculator** (data)
   - Evaluate mathematical expressions
   - Parameters: expression (string)

3. **get_time** (system)
   - Get current date/time in various formats
   - Parameters: format (enum: iso|unix|human), timezone (string)

4. **web_search** (web)
   - Search the web using DuckDuckGo
   - Parameters: query (string), num_results (number)

5. **read_url** (web)
   - Fetch and extract text from URLs
   - Parameters: url (string), max_length (number)

## Testing

### Unit Tests
Run the MCP server test suite:
```bash
python test_mcp_server.py
```

Tests verify:
- Server initialization
- Tool discovery (tools/list)
- Tool execution (tools/call)
- Error handling
- Ping health check
- Tool manifest retrieval

### Integration Tests
Test with a live server:

1. **Start the server:**
```bash
uvicorn jarvis.app.core.app:create_app --factory --reload
```

2. **Run the client demo:**
```bash
python test_mcp_client.py
```

This demonstrates:
- Connecting to MCP server
- Discovering tools
- Calling tools (calculator, get_time, execute_code)
- Handling results

### Manual Testing with curl

**Initialize:**
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "clientInfo": {"name": "curl-test", "version": "1.0"}
    },
    "id": 1
  }'
```

**List Tools:**
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 2
  }'
```

**Call Tool:**
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "calculator",
      "arguments": {"expression": "2 + 2"}
    },
    "id": 3
  }'
```

**Get Manifest:**
```bash
curl http://localhost:8000/mcp/manifest
```

## Error Handling

MCP server follows JSON-RPC 2.0 error conventions:

### Standard Errors
- `-32700` Parse error (invalid JSON)
- `-32600` Invalid Request
- `-32601` Method not found
- `-32602` Invalid params
- `-32603` Internal error

### MCP-Specific Errors
- `-32001` Tool not found
- `-32002` Tool execution error
- `-32003` Tool timeout

### Error Response Format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32601,
    "message": "Method not found: unknown_method",
    "data": {}
  }
}
```

## Adding New Tools

Tools added to the Tool Registry are automatically exposed via MCP:

1. **Define the tool** in `jarvis/app/llm/tools/`
2. **Register it** in the registry (see `init_tools.py`)
3. **Restart the server** - tool is now available via MCP

No MCP-specific code needed! The MCP server automatically:
- Converts tool schema to MCP format
- Exposes it via `tools/list`
- Enables invocation via `tools/call`

## Security Considerations

1. **No Authentication** (MVP)
   - Current implementation has no auth
   - Suitable for local development only
   - **Production:** Add JWT/API key authentication

2. **Tool Sandboxing**
   - `execute_code` runs in restricted environment
   - No file I/O, limited builtins
   - Timeout enforcement

3. **Rate Limiting**
   - Not implemented in MVP
   - **Production:** Add rate limiting middleware

4. **Input Validation**
   - Tool parameters validated by Tool Registry
   - JSON-RPC format validated by MCP server

## Integration with Agents

Agents can use MCP in two ways:

### 1. Direct Tool Registry (Current)
```python
# In agent_runner.py
tool_result = await self.tool_registry.execute(tool_name, tool_args)
```

### 2. Via MCP Protocol (Phase 3.3)
```python
# Future: Agent discovers tools via MCP
tools = await mcp_client.list_tools()
result = await mcp_client.call_tool("calculator", {"expression": "2+2"})
```

Phase 3.3 will implement agent-to-MCP integration for dynamic tool discovery.

## Files Created

- `jarvis/app/mcp/__init__.py` - Module exports
- `jarvis/app/mcp/protocol.py` - JSON-RPC/MCP protocol definitions
- `jarvis/app/mcp/server.py` - MCP server implementation
- `jarvis/app/api/routes/mcp.py` - FastAPI routes
- `test_mcp_server.py` - Unit tests
- `test_mcp_client.py` - Client demo

## Status

- ✅ Phase 3.1: Create MCP Server - **COMPLETE**
- ✅ Phase 3.2: Register MCP Tools - **COMPLETE**
- ⏳ Phase 3.3: Connect Agent to MCP - **PENDING**

All tools are registered and accessible via MCP protocol!
