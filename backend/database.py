"""
Shared MongoDB connection module.

All backend modules (server.py and services/*) import `db` from here instead
of creating their own Motor client. This avoids circular imports between
server.py and the service modules while giving services access to MongoDB
for persisting state (auto-trader risk state, monitored positions, trade
history, missed opportunities).
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
