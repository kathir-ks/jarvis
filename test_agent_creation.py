"""Test agent creation directly."""
import asyncio
import sys
import os

# Add the project to path
sys.path.insert(0, os.path.dirname(__file__))

async def test_agent_creation():
    try:
        # Set environment variables
        os.environ['JARVIS_MONGO_DSN'] = 'mongodb://localhost:27017'
        os.environ['JARVIS_REDIS_URL'] = 'redis://localhost:6379/0'
        os.environ['JARVIS_QDRANT_URL'] = 'http://localhost:6333'
        
        from jarvis.app.services.agents import AgentService
        from jarvis.app.models.agents import CreateAgentRequest
        
        service = AgentService()
        
        payload = CreateAgentRequest(
            agent_type="MASTER",
            config={"llm_provider": "openai", "model": "gpt-4"},
            tools_enabled=["web_search"]
        )
        
        print("Creating agent...")
        result = await service.create_agent(payload, user_id="test-user-001")
        print(f"Success! Agent ID: {result.agent_id}")
        print(f"Agent type: {result.agent_type}")
        print(f"Status: {result.status}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_agent_creation())
