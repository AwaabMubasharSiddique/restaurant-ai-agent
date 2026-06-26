"""Central configuration, loaded from environment / .env file.

Every secret (OpenAI key, Supabase keys) is read from the environment only.
Nothing is hard-coded, so the same image runs in dev, staging and prod by
swapping environment variables.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- Supabase (optional; falls back to in-memory store if unset) ---
    supabase_url: str | None = None
    supabase_key: str | None = None

    # --- Reservation capacity: simple per-slot counting for v1 ---
    max_reservations_per_slot: int = 10
    reservation_slot_minutes: int = 30
    opening_time: str = "11:00"  # HH:MM, 24h
    closing_time: str = "22:00"  # HH:MM, 24h
    # Parties this size or larger are handed to staff (set menu may apply).
    large_party_threshold: int = 8

    # --- RAG ---
    data_path: str = "data/restaurant_info.txt"
    faiss_index_path: str = "rag/faiss_index"
    retrieval_k: int = 4

    # --- Agent ---
    low_confidence_threshold: float = 0.6

    # --- API ---
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    rate_limit: str = "20/minute"
    restaurant_name: str = "The Olive Branch"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
