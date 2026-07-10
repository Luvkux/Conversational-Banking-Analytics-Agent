"""Central config loaded from .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    database_url: str = "postgresql+psycopg://banking:banking@localhost:5433/banking"

    chroma_dir: str = "./.chroma"

    max_retries: int = 2
    query_timeout_seconds: int = 10
    top_k_schema: int = 8
    top_k_fewshots: int = 6


settings = Settings()
