import os
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Enterprise AI RAG Platform"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = Field(default="SUPER_SECRET_JWT_SIGNING_KEY_DO_NOT_USE_IN_PRODUCTION_1234567890")
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
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS settings
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


    # Vector DB (Qdrant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None

    # Gemini Settings
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

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
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
