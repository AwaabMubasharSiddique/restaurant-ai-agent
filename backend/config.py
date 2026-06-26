from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    supabase_url: str | None = None
    supabase_key: str | None = None

    restaurant_tables: list[dict] = [
        {"id": "T1", "seats": 4},
        {"id": "T2", "seats": 4},
        {"id": "T3", "seats": 8},
    ]

    seating_duration_minutes: int = 90
    reservation_slot_minutes: int = 30
    opening_time: str = "11:00"
    closing_time: str = "22:00"

    reservation_edit_window_minutes: int = 30

    max_advance_days: int = 30

    data_path: str = "data/restaurant_info.txt"
    faiss_index_path: str = "rag/faiss_index"
    retrieval_k: int = 4

    menu_retrieval_k: int = 10

    low_confidence_threshold: float = 0.6

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
