from app.core.database import engine, Base
# Import all models to ensure they are registered with Base.metadata
from app.core.logging import logger

async def init_db() -> None:
    try:
        logger.info("Starting database table initialization...")
        async with engine.begin() as conn:
            # Recreate tables if they do not exist
            await conn.run_sync(Base.metadata.create_all)
            # Safe schema migration: add rating column if not exists
            from sqlalchemy import text
            try:
                await conn.execute(text("ALTER TABLE query_logs ADD COLUMN rating INTEGER"))
                logger.info("Schema migration: Added 'rating' column to 'query_logs' table.")
            except Exception:
                pass # Already exists or table not ready
            
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"))
                # Existing users should be marked as verified so they don't get locked out
                await conn.execute(text("UPDATE users SET email_verified = TRUE"))
                logger.info("Schema migration: Added 'email_verified' column to 'users' table.")
            except Exception:
                pass # Already exists or table not ready

        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {str(e)}")
        raise e
