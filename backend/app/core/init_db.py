from app.core.database import engine, Base
# Import all models to ensure they are registered with Base.metadata
from app.core.logging import logger

async def init_db() -> None:
    try:
        logger.info("Starting database table initialization...")
        # Recreate tables if they do not exist
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from sqlalchemy import text
        # Safe schema migration: add rating column if not exists
        async with engine.begin() as conn:
            try:
                await conn.execute(text("ALTER TABLE query_logs ADD COLUMN rating INTEGER"))
                logger.info("Schema migration: Added 'rating' column to 'query_logs' table.")
            except Exception:
                pass # Already exists or table not ready
            
        async with engine.begin() as conn:
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"))
                # Existing users should be marked as verified so they don't get locked out
                await conn.execute(text("UPDATE users SET email_verified = TRUE"))
                logger.info("Schema migration: Added 'email_verified' column to 'users' table.")
            except Exception:
                pass # Already exists or table not ready

        async with engine.begin() as conn:
            try:
                await conn.execute(text("CREATE INDEX IF NOT EXISTS doc_chunks_content_fts_idx ON document_chunks USING gin(to_tsvector('english', content))"))
                logger.info("Schema migration: Created GIN FTS index on 'document_chunks'.")
            except Exception as e:
                logger.warning(f"Could not create FTS index: {e}")

        async with engine.begin() as conn:
            try:
                await conn.execute(text("ALTER TABLE messages ADD COLUMN query_log_id UUID REFERENCES query_logs(id) ON DELETE SET NULL"))
                logger.info("Schema migration: Added 'query_log_id' column to 'messages' table.")
            except Exception:
                pass # Already exists or table not ready


        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {str(e)}")
        raise e
