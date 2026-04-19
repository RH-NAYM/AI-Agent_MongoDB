"""
app/config.py  –  Central configuration via pydantic-settings.
All values are read from environment variables or .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "retail_agent_db"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5"
    ollama_embed_model: str = "nomic-embed-text"

    # Embedding backend
    embed_backend: str = "ollama"          # "ollama" | "sentence_transformers"
    embed_st_model: str = "all-MiniLM-L6-v2"
    embed_dimension: int = 768

    # Agent behaviour
    max_retry_attempts: int = 3
    memory_window: int = 10
    vector_top_k: int = 5

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
