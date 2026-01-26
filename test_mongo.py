import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def test_mongo():
    try:
        client = AsyncIOMotorClient('mongodb://localhost:27017')
        result = await client.admin.command('ping')
        print(f"MongoDB connection successful: {result}")
        
        # Test database access
        db = client['jarvis']
        collections = await db.list_collection_names()
        print(f"Collections: {collections}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mongo())
