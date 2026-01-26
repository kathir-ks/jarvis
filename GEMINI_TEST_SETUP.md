# Testing Gemini API with Tool Calling

## Quick Setup

### 1. Get Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated API key

### 2. Configure API Key

**Option A: Environment Variable**
```bash
export JARVIS_GEMINI_API_KEY='your-api-key-here'
```

**Option B: .env File**
Edit `.env` in the project root and add:
```bash
JARVIS_GEMINI_API_KEY=your-api-key-here
```

### 3. Run the Test

```bash
python test_gemini_tools.py
```

## What the Test Does

The test suite includes 3 test cases:

### Test 1: Basic Chat
- Simple greeting without tools
- Verifies Gemini API connectivity
- Confirms basic chat functionality

### Test 2: Tool Calling (Calculator)
- Asks: "What is the square root of 256?"
- Gemini should:
  1. Recognize it needs the calculator tool
  2. Call `calculator(expression="sqrt(256)")`
  3. Receive result: 16.0
  4. Respond with a natural language answer

### Test 3: Multiple Tools
- Asks: "What is 15 * 23, and what time is it in UTC?"
- Gemini should:
  1. Call `calculator(expression="15 * 23")`
  2. Call `get_time(format="human", timezone="UTC")`
  3. Combine both results into a coherent answer

## Expected Output

```
Starting Gemini + Tools Integration Tests
======================================================================
✓ Gemini API Key: AIzaSy...
✓ Model: gemini-1.5-flash

======================================================================
Test 1: Basic Gemini Chat (No Tools)
======================================================================
✓ Gemini Response:
  Provider: gemini
  Model: gemini-1.5-flash
  Content: Hello! How can I help you today?
  Finish Reason: STOP
  Tokens: 45 total

======================================================================
Test 2: Gemini with Tool Calling
======================================================================

📤 Calling Gemini with tools available...
✓ Gemini Response:
  Provider: gemini
  Model: gemini-1.5-flash
  Content:
  Finish Reason: STOP
  🔧 Tool Calls: 1

  Tool Call #1:
    Function: calculator
    Arguments: {
      "expression": "sqrt(256)"
    }

  ⚙️ Executing tool: calculator
  ✓ Tool Result: {
    "success": true,
    "expression": "sqrt(256)",
    "result": 16.0,
    "error": null
  }

📤 Getting final response from Gemini...
✓ Final Response:
  The square root of 256 is 16.0.

======================================================================
Test 3: Gemini with Multiple Tools
======================================================================
...

======================================================================
Test Summary
======================================================================
Basic Chat:        ✓ PASS
Tool Calling:      ✓ PASS
Multiple Tools:    ✓ PASS
======================================================================
```

## Troubleshooting

### Error: "No Gemini API key configured!"
- Make sure you've set `JARVIS_GEMINI_API_KEY`
- If using .env file, make sure it's in the project root
- Try restarting your terminal/IDE

### Error: "API key not valid"
- Verify you copied the full API key
- Check for extra spaces or quotes
- Generate a new key if needed

### Error: "Rate limit exceeded"
- Gemini free tier has limits
- Wait a few minutes and try again
- Consider upgrading to paid tier

### Error: "Module not found: google.generativeai"
- Run: `pip install google-generativeai`
- Already in requirements.txt

## Tool Calling Implementation

The Gemini provider now supports function calling:

1. **Tool Schema Conversion**: Automatically converts OpenAI-format tools to Gemini's FunctionDeclaration format
2. **Function Call Detection**: Extracts function calls from Gemini responses
3. **Format Normalization**: Converts Gemini function calls to OpenAI-compatible format for consistency
4. **Multi-turn Conversations**: Supports tool results being fed back for final answer synthesis

## Available Tools

All 5 tools are available to Gemini:

1. **calculator** - Evaluate math expressions
   ```python
   calculator(expression="sqrt(144) + 10")
   # Returns: {"result": 22.0}
   ```

2. **get_time** - Get current time
   ```python
   get_time(format="human", timezone="UTC")
   # Returns: {"formatted": "2026-01-20 19:30:00 UTC"}
   ```

3. **execute_code** - Safe Python execution
   ```python
   execute_code(code="print('Hello!')")
   # Returns: {"stdout": "Hello!\n"}
   ```

4. **web_search** - DuckDuckGo search
   ```python
   web_search(query="Python asyncio", num_results=3)
   # Returns: [{"title": "...", "url": "...", "snippet": "..."}]
   ```

5. **read_url** - Fetch web content
   ```python
   read_url(url="https://example.com", max_length=1000)
   # Returns: {"content": "...", "url": "..."}
   ```

## Comparison: Gemini vs OpenAI

Both providers now support identical tool calling features:

| Feature | OpenAI | Gemini |
|---------|--------|--------|
| Function Calling | ✅ | ✅ |
| Multiple Tools | ✅ | ✅ |
| Parallel Tool Calls | ✅ | ✅* |
| Tool Results | ✅ | ✅ |
| Schema Conversion | Native | Auto-converted |

*Gemini may call multiple tools in sequence rather than parallel

## Next Steps

After successful testing:
1. Configure for production use
2. Implement tool choice strategies
3. Add error recovery and retries
4. Monitor token usage and costs
