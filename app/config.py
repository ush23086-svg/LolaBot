from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OPENROUTER_DEFAULT_MODEL = "meta-llama/llama-3.2-3b-instruct:free"
OPENROUTER_LEGACY_MODEL_ALIASES = {
    "google/gemma-3-27b-it:free": OPENROUTER_DEFAULT_MODEL,
    "google/gemma-3n-e4b-it:free": OPENROUTER_DEFAULT_MODEL,
}


class Settings(BaseSettings):
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    openrouter_api_key_1: str | None = Field(default=None, alias="OPENROUTER_API_KEY_1")
    openrouter_api_key_2: str | None = Field(default=None, alias="OPENROUTER_API_KEY_2")
    openrouter_api_key_3: str | None = Field(default=None, alias="OPENROUTER_API_KEY_3")
    openrouter_model: str = Field(
        default=OPENROUTER_DEFAULT_MODEL,
        alias="OPENROUTER_MODEL",
    )
    codmunity_timeout: int = Field(default=15, alias="CODMUNITY_TIMEOUT")
    bot_name: str = Field(default="Lola", alias="BOT_NAME")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def openrouter_api_keys(self) -> list[str]:
        keys = [
            self.openrouter_api_key_1,
            self.openrouter_api_key_2,
            self.openrouter_api_key_3,
        ]
        clean_keys: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if not key:
                continue
            key = key.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            clean_keys.append(key)
        return clean_keys

    @property
    def openrouter_model_name(self) -> str:
        model = self.openrouter_model.strip()
        return OPENROUTER_LEGACY_MODEL_ALIASES.get(model, model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
