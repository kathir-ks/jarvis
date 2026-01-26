"""Test script for LLM provider integration (OpenAI and Gemini)."""
import asyncio
import os
import sys

# Add the project to path
sys.path.insert(0, os.path.dirname(__file__))


async def test_openai_provider():
    """Test OpenAI provider integration."""
    print("\n" + "="*60)
    print("Testing OpenAI Provider")
    print("="*60)
    
    api_key = os.getenv("JARVIS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ SKIPPED: JARVIS_OPENAI_API_KEY or OPENAI_API_KEY not set")
        return False
    
    try:
        from jarvis.app.llm.providers import OpenAIProvider
        
        provider = OpenAIProvider(
            api_key=api_key,
            default_model="gpt-4o-mini"
        )
        
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": "Say 'Hello from OpenAI!' in a creative way."}
        ]
        
        print(f"Provider: {provider.name}")
        print(f"Sending request...")
        
        result = await provider.chat(messages)
        
        print(f"\n✅ SUCCESS!")
        print(f"Model: {result.model}")
        print(f"Provider: {result.provider}")
        print(f"Response: {result.content}")
        print(f"Finish Reason: {result.finish_reason}")
        if result.usage:
            print(f"Tokens Used: {result.usage}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_gemini_provider():
    """Test Gemini provider integration."""
    print("\n" + "="*60)
    print("Testing Gemini Provider")
    print("="*60)
    
    api_key = os.getenv("JARVIS_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ SKIPPED: JARVIS_GEMINI_API_KEY or GEMINI_API_KEY not set")
        return False
    
    try:
        from jarvis.app.llm.providers import GeminiProvider
        
        provider = GeminiProvider(
            api_key=api_key,
            default_model="gemini-1.5-flash"
        )
        
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": "Say 'Hello from Gemini!' in a creative way."}
        ]
        
        print(f"Provider: {provider.name}")
        print(f"Sending request...")
        
        result = await provider.chat(messages)
        
        print(f"\n✅ SUCCESS!")
        print(f"Model: {result.model}")
        print(f"Provider: {result.provider}")
        print(f"Response: {result.content}")
        print(f"Finish Reason: {result.finish_reason}")
        if result.usage:
            print(f"Tokens Used: {result.usage}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_router():
    """Test LLM router with automatic provider selection."""
    print("\n" + "="*60)
    print("Testing LLM Router")
    print("="*60)
    
    try:
        from jarvis.app.llm.router import LLMRouter
        
        router = LLMRouter()
        
        print(f"Available providers: {list(router.providers.keys())}")
        print(f"Default provider: {router.default_provider}")
        
        if not router.providers:
            print("❌ No providers configured!")
            return False
        
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": "Explain in one sentence what an AI agent is."}
        ]
        
        # Test with default provider
        print(f"\nTesting with default provider ({router.default_provider})...")
        result = await router.call(messages)
        print(f"✅ Response from {result.provider}: {result.content[:100]}...")
        
        # Test with explicit provider selection if multiple available
        for provider_name in router.providers.keys():
            if provider_name != router.default_provider:
                print(f"\nTesting with explicit provider ({provider_name})...")
                result = await router.call(messages, config={"provider": provider_name})
                print(f"✅ Response from {result.provider}: {result.content[:100]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("🤖 Jarvis LLM Provider Integration Tests")
    print("="*60)
    
    results = {
        "OpenAI": await test_openai_provider(),
        "Gemini": await test_gemini_provider(),
        "Router": await test_llm_router(),
    }
    
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED/SKIPPED"
        print(f"{test_name}: {status}")
    
    total_passed = sum(1 for v in results.values() if v)
    total_tests = len(results)
    
    print(f"\nTotal: {total_passed}/{total_tests} tests passed")
    
    if total_passed == 0:
        print("\n⚠️  NOTE: To run these tests, set environment variables:")
        print("   - JARVIS_OPENAI_API_KEY or OPENAI_API_KEY")
        print("   - JARVIS_GEMINI_API_KEY or GEMINI_API_KEY")


if __name__ == "__main__":
    asyncio.run(main())
