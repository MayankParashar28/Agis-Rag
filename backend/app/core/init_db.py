from app.core.database import engine, Base
# Import all models so they are registered with Base.metadata before create_all
import app.models  # noqa: F401
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


        # Add any model column the live database is missing. create_all only
        # creates whole tables, so a column added to a model later (e.g.
        # evaluations.method) never reached databases created before it, and
        # every query on that table failed with "column does not exist".
        try:
            async with engine.begin() as conn:
                added = await conn.run_sync(_add_missing_columns)
                for name in added:
                    logger.info(f"Schema migration: added missing column {name}.")
        except Exception as e:
            logger.warning(f"Could not add missing columns: {e}")

        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {str(e)}")
        raise e


def _add_missing_columns(sync_conn) -> list:
    """Add nullable versions of model columns that are absent in the database."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    dialect = sync_conn.dialect
    existing_tables = set(inspector.get_table_names())
    added = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present or column.primary_key:
                continue
            col_type = column.type.compile(dialect=dialect)
            # Always nullable: a NOT NULL column cannot be added to a table
            # that already has rows without a default.
            sync_conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'))
            added.append(f"{table.name}.{column.name}")
    return added
