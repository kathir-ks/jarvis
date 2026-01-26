"""
Test script for Vector Memory and OpenAI integration.

Prerequisites:
1. Docker services running: docker-compose up -d
2. OpenAI API key set: export JARVIS_OPENAI_API_KEY=sk-...
3. Dependencies installed: pip install -r requirements.txt

Run: python test_vector_memory.py
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_embeddings():
    """Test OpenAI embedding generation."""
    print("\n" + "=" * 60)
    print("  TEST 1: OpenAI Embeddings")
    print("=" * 60)
    
    from jarvis.app.llm.embeddings import EmbeddingProvider
    
    try:
        provider = EmbeddingProvider()
        print("[OK] EmbeddingProvider initialized")
        
        # Test single embedding
        text = "I want to find the best laptop for programming"
        result = await provider.embed(text)
        
        print(f"[OK] Generated embedding for: '{text[:50]}...'")
        print(f"     Model: {result.model}")
        print(f"     Dimensions: {result.dimensions}")
        print(f"     Tokens used: {result.tokens_used}")
        print(f"     Vector preview: [{result.vector[0]:.6f}, {result.vector[1]:.6f}, ...]")
        
        # Test batch embedding
        texts = [
            "Find me a good coffee shop nearby",
            "What's the weather like today?",
            "Book a flight to New York"
        ]
        batch_results = await provider.embed_batch(texts)
        print(f"[OK] Batch embedding for {len(texts)} texts")
        for i, res in enumerate(batch_results):
            print(f"     Text {i+1}: {res.dimensions} dimensions")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Embedding test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_vector_memory():
    """Test Qdrant vector memory storage and retrieval."""
    print("\n" + "=" * 60)
    print("  TEST 2: Vector Memory (Qdrant)")
    print("=" * 60)
    
    from jarvis.app.db.vector_memory import VectorMemoryService
    
    try:
        service = VectorMemoryService()
        print("[OK] VectorMemoryService initialized")
        
        # Initialize collections
        await service.initialize_collections()
        print("[OK] Collections initialized")
        
        test_user_id = "test_user_001"
        test_agent_id = "test_agent_001"
        
        # Store some test interactions
        print("\n--- Storing test interactions ---")
        
        interaction1 = await service.store_interaction(
            content="I'm looking for a new laptop for software development, preferably with good battery life",
            user_id=test_user_id,
            agent_id=test_agent_id,
            interaction_type="user_message",
        )
        print(f"[OK] Stored interaction: {interaction1.id}")
        
        interaction2 = await service.store_interaction(
            content="Based on your requirements, I recommend the MacBook Pro M3 or ThinkPad X1 Carbon. Both have excellent battery life and powerful processors for development.",
            user_id=test_user_id,
            agent_id=test_agent_id,
            interaction_type="assistant_response",
        )
        print(f"[OK] Stored interaction: {interaction2.id}")
        
        interaction3 = await service.store_interaction(
            content="What about gaming laptops? Can they be good for programming too?",
            user_id=test_user_id,
            agent_id=test_agent_id,
            interaction_type="user_message",
        )
        print(f"[OK] Stored interaction: {interaction3.id}")
        
        # Store a discovery
        print("\n--- Storing test discovery ---")
        
        discovery = await service.store_discovery(
            content="Top 10 Laptops for Developers 2026: A comprehensive guide covering performance, battery life, and portability",
            user_id=test_user_id,
            agent_id=test_agent_id,
            source="web_search",
            url="https://example.com/best-dev-laptops",
            tags=["laptop", "development", "technology"],
        )
        print(f"[OK] Stored discovery: {discovery.id}")
        
        # Store some knowledge
        print("\n--- Storing test knowledge ---")
        
        knowledge = await service.store_knowledge(
            content="User prefers laptops with good battery life and is interested in software development",
            agent_id=test_agent_id,
            knowledge_type="preference",
            confidence=0.9,
        )
        print(f"[OK] Stored knowledge: {knowledge.id}")
        
        # Test search
        print("\n--- Testing semantic search ---")
        
        # Search interactions
        search_query = "laptop recommendations for coding"
        results = await service.search_interactions(
            query=search_query,
            user_id=test_user_id,
            limit=5,
            score_threshold=0.3,
        )
        print(f"\n[OK] Search for '{search_query}':")
        print(f"     Found {results.total_found} results")
        for entry in results.entries:
            print(f"     - Score {entry.score:.3f}: {entry.content[:60]}...")
        
        # Search discoveries
        discovery_results = await service.search_discoveries(
            query="best laptops guide",
            user_id=test_user_id,
            limit=5,
            score_threshold=0.3,
        )
        print(f"\n[OK] Discovery search found {discovery_results.total_found} results")
        
        # Test get_recent_context
        print("\n--- Testing context retrieval ---")
        
        context = await service.get_recent_context(
            user_id=test_user_id,
            agent_id=test_agent_id,
            query="What laptops should I buy?",
        )
        print(f"[OK] Context retrieved:")
        print(f"     Interactions: {len(context['interactions'])}")
        print(f"     Discoveries: {len(context['discoveries'])}")
        print(f"     Knowledge: {len(context['knowledge'])}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Vector memory test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_call():
    """Test direct LLM call through router."""
    print("\n" + "=" * 60)
    print("  TEST 3: LLM Router (OpenAI)")
    print("=" * 60)
    
    from jarvis.app.llm.router import LLMRouter
    
    try:
        router = LLMRouter()
        print("[OK] LLMRouter initialized")
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Respond briefly."},
            {"role": "user", "content": "What is 2 + 2? Reply with just the number."},
        ]
        
        config = {
            "model": "gpt-4o-mini",
            "temperature": 0.1,
            "max_tokens": 50,
        }
        
        print(f"[...] Calling LLM with model: {config['model']}")
        result = await router.call(messages, config)
        
        print(f"[OK] LLM Response received:")
        print(f"     Provider: {result.provider}")
        print(f"     Model: {result.model}")
        print(f"     Content: {result.content}")
        print(f"     Finish reason: {result.finish_reason}")
        if result.usage:
            print(f"     Tokens: {result.usage}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] LLM call test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_prompt_builder():
    """Test prompt building with context."""
    print("\n" + "=" * 60)
    print("  TEST 4: Prompt Builder")
    print("=" * 60)
    
    from jarvis.app.llm.prompt_builder import PromptBuilder
    from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType, AgentStatus
    
    try:
        builder = PromptBuilder()
        print("[OK] PromptBuilder initialized")
        
        # Create mock agent
        agent = Agent(
            _id="test_agent_001",
            user_id="test_user_001",
            agent_type=AgentType.MASTER,
            status=AgentStatus.RUNNING,
            config=AgentConfig(),
            short_term_memory=[
                {"role": "user", "content": "Hello, I need help finding a laptop", "timestamp": "2026-01-08T10:00:00"},
                {"role": "assistant", "content": "I'd be happy to help! What will you use it for?", "timestamp": "2026-01-08T10:00:05"},
            ],
            context={"user_name": "TestUser", "preference": "tech products"},
        )
        
        # Mock long-term context
        from jarvis.app.db.vector_memory import MemoryEntry
        long_term_context = {
            "interactions": [
                MemoryEntry(
                    id="mem1",
                    content="User previously searched for MacBook Pro reviews",
                    score=0.85,
                ),
            ],
            "discoveries": [
                MemoryEntry(
                    id="disc1",
                    content="Best laptops for developers 2026 article",
                    metadata={"source": "web_search"},
                    score=0.78,
                ),
            ],
            "knowledge": [
                MemoryEntry(
                    id="know1",
                    content="User prefers Apple products",
                    metadata={"knowledge_type": "preference", "confidence": 0.9},
                    score=0.92,
                ),
            ],
        }
        
        incoming_message = {
            "type": "message",
            "content": "What laptop do you recommend for programming?",
        }
        
        messages = builder.build_agent_messages(agent, incoming_message, long_term_context)
        
        print(f"[OK] Built {len(messages)} messages for LLM:")
        for i, msg in enumerate(messages):
            role = msg["role"]
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            print(f"     [{i}] {role}: {content}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Prompt builder test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_full_flow():
    """Test full agent flow with vector memory and LLM."""
    print("\n" + "=" * 60)
    print("  TEST 5: Full Integration Flow")
    print("=" * 60)
    
    from jarvis.app.llm.router import LLMRouter
    from jarvis.app.llm.prompt_builder import PromptBuilder
    from jarvis.app.db.vector_memory import VectorMemoryService
    from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType, AgentStatus
    
    try:
        # Initialize components
        vector_memory = VectorMemoryService()
        await vector_memory.initialize_collections()
        llm_router = LLMRouter()
        prompt_builder = PromptBuilder()
        
        print("[OK] All components initialized")
        
        # Create mock agent
        agent = Agent(
            _id="integration_test_agent",
            user_id="integration_test_user",
            agent_type=AgentType.MASTER,
            status=AgentStatus.RUNNING,
            config=AgentConfig(
                model="gpt-4o-mini",
                temperature=0.7,
                max_tokens=500,
            ),
            short_term_memory=[],
            context={},
        )
        
        # Simulate conversation
        user_messages = [
            "Hi! I'm looking for a good restaurant in downtown for a business dinner.",
            "It should be Italian cuisine, with a quiet atmosphere.",
        ]
        
        for user_msg in user_messages:
            print(f"\n[USER] {user_msg}")
            
            # Store user message in vector memory
            await vector_memory.store_interaction(
                content=user_msg,
                user_id=agent.user_id,
                agent_id=agent.agent_id,
                interaction_type="user_message",
            )
            
            # Get relevant context
            context = await vector_memory.get_recent_context(
                user_id=agent.user_id,
                agent_id=agent.agent_id,
                query=user_msg,
            )
            
            # Build prompt with context
            incoming = {"type": "message", "content": user_msg}
            messages = prompt_builder.build_agent_messages(agent, incoming, context)
            
            # Call LLM
            config = {
                "model": agent.config.model,
                "temperature": agent.config.temperature,
                "max_tokens": agent.config.max_tokens,
            }
            result = await llm_router.call(messages, config)
            
            print(f"[JARVIS] {result.content}")
            
            # Store assistant response
            await vector_memory.store_interaction(
                content=result.content,
                user_id=agent.user_id,
                agent_id=agent.agent_id,
                interaction_type="assistant_response",
            )
            
            # Update short-term memory
            agent.short_term_memory.append({"role": "user", "content": user_msg})
            agent.short_term_memory.append({"role": "assistant", "content": result.content})
        
        print("\n[OK] Full integration flow completed successfully!")
        return True
        
    except Exception as e:
        print(f"[FAIL] Full flow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  JARVIS VECTOR MEMORY & LLM TEST SUITE")
    print("=" * 60)
    
    # Check for API key
    api_key = os.environ.get("JARVIS_OPENAI_API_KEY")
    if not api_key:
        print("\n[WARN] JARVIS_OPENAI_API_KEY not set!")
        print("       Set it with: export JARVIS_OPENAI_API_KEY=sk-...")
        print("       Or on Windows: set JARVIS_OPENAI_API_KEY=sk-...")
        print("\n       Attempting to continue anyway (will fail if key not in .env)")
    else:
        print(f"\n[OK] API key found: {api_key[:10]}...")
    
    results = {}
    
    # Run tests
    results["embeddings"] = await test_embeddings()
    results["vector_memory"] = await test_vector_memory()
    results["llm_call"] = await test_llm_call()
    results["prompt_builder"] = await test_prompt_builder()
    results["full_flow"] = await test_full_flow()
    
    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {name}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    print("=" * 60 + "\n")
    
    return all(results.values())


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
