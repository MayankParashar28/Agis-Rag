import asyncio
from app.core.init_db import init_db

async def main():
    await init_db()

if __name__ == "__main__":
    asyncio.run(main())
