import asyncio
from app.core.database import engine
from sqlalchemy import text

async def main():
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("UPDATE users SET email_verified = TRUE"))
            print("Successfully added email_verified column")
    except Exception as e:
        print(f"Failed to add column: {e}")

if __name__ == "__main__":
    asyncio.run(main())
