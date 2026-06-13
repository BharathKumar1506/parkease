import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

client = None
db = None

async def connect_db():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["parkease"]
    await client.admin.command("ping")
    print("✅ MongoDB connected successfully")

async def disconnect_db():
    global client
    if client:
        client.close()

def get_db():
    return db
