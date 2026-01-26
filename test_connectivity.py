"""
Simple connectivity test for Jarvis platform services.
Tests MongoDB, Redis, and Qdrant connections.

Run: python test_connectivity.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_mongodb():
    """Test MongoDB connection."""
    print("\n[1] Testing MongoDB...")
    try:
        from pymongo import MongoClient
        
        dsn = os.environ.get("JARVIS_MONGO_DSN", "mongodb://localhost:27017")
        client = MongoClient(dsn, serverSelectionTimeoutMS=5000)
        
        # Ping the server
        client.admin.command('ping')
        
        # List databases
        dbs = client.list_database_names()
        print(f"    ✅ Connected to MongoDB")
        print(f"    Databases: {dbs}")
        
        client.close()
        return True
    except Exception as e:
        print(f"    ❌ MongoDB connection failed: {e}")
        return False


def test_redis():
    """Test Redis connection."""
    print("\n[2] Testing Redis...")
    try:
        import redis
        
        url = os.environ.get("JARVIS_REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url)
        
        # Ping
        result = client.ping()
        print(f"    ✅ Connected to Redis (ping={result})")
        
        # Test set/get
        client.set("jarvis_test", "hello")
        value = client.get("jarvis_test")
        print(f"    Test key: {value}")
        client.delete("jarvis_test")
        
        return True
    except Exception as e:
        print(f"    ❌ Redis connection failed: {e}")
        return False


def test_qdrant():
    """Test Qdrant connection."""
    print("\n[3] Testing Qdrant...")
    try:
        from qdrant_client import QdrantClient
        
        url = os.environ.get("JARVIS_QDRANT_URL", "http://localhost:6333")
        client = QdrantClient(url=url)
        
        # Get collections
        collections = client.get_collections()
        print(f"    ✅ Connected to Qdrant")
        print(f"    Collections: {[c.name for c in collections.collections]}")
        
        client.close()
        return True
    except Exception as e:
        print(f"    ❌ Qdrant connection failed: {e}")
        return False


def test_openai():
    """Test OpenAI API key."""
    print("\n[4] Testing OpenAI API...")
    
    api_key = os.environ.get("JARVIS_OPENAI_API_KEY")
    if not api_key:
        print("    ⚠️  JARVIS_OPENAI_API_KEY not set")
        print("    Set with: $env:JARVIS_OPENAI_API_KEY='sk-...'")
        return False
    
    if not api_key.startswith("sk-"):
        print(f"    ⚠️  API key format looks incorrect (should start with 'sk-')")
        return False
    
    try:
        from openai import OpenAI
        
        client = OpenAI(api_key=api_key)
        
        # Simple test call
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'OK' and nothing else."}],
            max_tokens=5,
        )
        
        content = response.choices[0].message.content
        print(f"    ✅ OpenAI API working")
        print(f"    Test response: {content}")
        
        return True
    except Exception as e:
        print(f"    ❌ OpenAI API failed: {e}")
        return False


def main():
    """Run all connectivity tests."""
    print("\n" + "=" * 50)
    print("  JARVIS CONNECTIVITY TESTS")
    print("=" * 50)
    
    results = {
        "MongoDB": test_mongodb(),
        "Redis": test_redis(),
        "Qdrant": test_qdrant(),
        "OpenAI": test_openai(),
    }
    
    print("\n" + "=" * 50)
    print("  SUMMARY")
    print("=" * 50)
    
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
    
    passed = sum(1 for v in results.values() if v)
    print(f"\n  Total: {passed}/{len(results)} services connected")
    print("=" * 50 + "\n")
    
    # If OpenAI failed, print instructions
    if not results["OpenAI"]:
        print("To fix OpenAI, set your API key:")
        print('  $env:JARVIS_OPENAI_API_KEY="sk-your-key-here"')
        print("Then run: python test_vector_memory.py")
    
    return all(results.values())


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
