import os
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Aegis RAG"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = Field(...)  # REQUIRED — no default to prevent JWT forgery
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # PostgreSQL Connection
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "rag_user"
    POSTGRES_PASSWORD: str = "rag_password"
    POSTGRES_DB: str = "enterprise_rag"
    POSTGRES_PORT: int = 5432
    DATABASE_URI: Optional[str] = None

    @field_validator("DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
            return v
        
        # Read from field values in info.data
        data = info.data
        user = data.get("POSTGRES_USER")
        password = data.get("POSTGRES_PASSWORD")
        server = data.get("POSTGRES_SERVER")
        port = data.get("POSTGRES_PORT")
        db = data.get("POSTGRES_DB")
        
        return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"

    # Sync Database URI for utilities/RAGAS that require synchronous drivers
    SYNC_DATABASE_URI: Optional[str] = None

    @field_validator("SYNC_DATABASE_URI", mode="before")
    @classmethod
    def assemble_sync_db_connection(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            if v.startswith("postgresql+asyncpg://"):
                return v.replace("postgresql+asyncpg://", "postgresql://", 1)
            return v
        data = info.data
        user = data.get("POSTGRES_USER")
        password = data.get("POSTGRES_PASSWORD")
        server = data.get("POSTGRES_SERVER")
        port = data.get("POSTGRES_PORT")
        db = data.get("POSTGRES_DB")
        return f"postgresql://{user}:{password}@{server}:{port}/{db}"

    # Redis Connection
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery settings
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def assemble_celery_broker(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            url = v
        else:
            url = info.data.get("REDIS_URL", "redis://localhost:6379/0")
        
        if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}ssl_cert_reqs=CERT_NONE"
        return url

    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    @classmethod
    def assemble_celery_backend(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            url = v
        else:
            url = info.data.get("REDIS_URL", "redis://localhost:6379/0")
            
        if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}ssl_cert_reqs=CERT_NONE"
        return url

    # CORS settings
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


    # --- Models -------------------------------------------------------------
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"
    EMBEDDING_DIM: int = 1024          # must match EMBEDDING_MODEL's output size
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    OPENAI_MODEL: str = "gpt-4o"

    # --- Retrieval tuning ---------------------------------------------------
    # Candidates pulled from each of the dense and sparse retrievers before fusion.
    RETRIEVAL_TOP_K: int = 15
    # Chunks kept after cross-encoder reranking and handed to the LLM.
    RERANK_TOP_N: int = 5
    # Minimum rerank score a chunk must reach to be shown to the LLM. The
    # cross-encoder emits sigmoid scores that run far lower than an intuitive
    # 0-1 "percent relevant" reading, so a high gate silently discards chunks
    # that do answer the question. Raise this only with measured results.
    RERANK_SCORE_THRESHOLD: float = 0.05

    # --- Ingestion ----------------------------------------------------------
    MAX_UPLOAD_SIZE_MB: int = 50
    DEFAULT_CHUNK_SIZE: int = 1000
    DEFAULT_CHUNK_OVERLAP: int = 200

    # --- Rate limiting ------------------------------------------------------
    RATE_LIMIT: str = "100/minute"

    # --- Web search ---------------------------------------------------------
    # When no TAVILY_API_KEY is configured, web search returns no results
    # rather than inventing them. Never serve fabricated sources to users.
    WEB_SEARCH_MAX_RESULTS: int = 3

    # Vector DB (Qdrant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None

    # Gemini Settings
    GEMINI_API_KEY: Optional[str] = None
    # gemini-1.5-flash and gemini-2.5-flash are retired - they 404 on the
    # OpenAI-compatible endpoint. This default is verified to stream, which
    # the chat endpoint requires (it calls completions with stream=True).
    GEMINI_MODEL: str = "gemini-3.5-flash"
    # Used as the RAGAS embeddings model when Gemini is the judge. RAGAS needs
    # embeddings as well as a chat model for answer_relevancy/context_precision.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    GEMINI_OPENAI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # LlamaParse & LlamaIndex
    LLAMAPARSE_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # Google Authentication
    GOOGLE_CLIENT_ID: Optional[str] = None

    # Web Search Options
    TAVILY_API_KEY: Optional[str] = None

    # Neon Auth Settings
    NEON_AUTH_BASE_URL: Optional[str] = None
    NEON_AUTH_COOKIE_SECRET: Optional[str] = None

    # Email Settings
    EMAIL_API_KEY: Optional[str] = None
    EMAIL_FROM_ADDRESS: str = "onboarding@resend.dev"


    model_config = SettingsConfigDict(
        # Read the repo-root .env as well as backend/.env, so the file the README
        # tells you to create at the project root is actually picked up no matter
        # which directory the process is started from. Later entries win.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
