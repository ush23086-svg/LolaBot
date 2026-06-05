from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OPENROUTER_DEFAULT_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_LEGACY_MODEL_ALIASES = {
    "google/gemma-3-27b-it:free": OPENROUTER_DEFAULT_MODEL,
    "google/gemma-3n-e4b-it:free": OPENROUTER_DEFAULT_MODEL,
    "meta-llama/llama-3.2-3b-instruct:free": OPENROUTER_DEFAULT_MODEL,
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
    openrouter_model_1: str | None = Field(default=None, alias="OPENROUTER_MODEL_1")
    openrouter_model_2: str | None = Field(default=None, alias="OPENROUTER_MODEL_2")
    openrouter_model_3: str | None = Field(default=None, alias="OPENROUTER_MODEL_3")
    openrouter_vision_model_1: str | None = Field(
        default=None,
        alias="OPENROUTER_VISION_MODEL_1",
    )
    openrouter_vision_model_2: str | None = Field(
        default=None,
        alias="OPENROUTER_VISION_MODEL_2",
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
    def openrouter_models(self) -> list[str]:
        models = [
            self.openrouter_model_1,
            self.openrouter_model_2,
            self.openrouter_model_3,
            self.openrouter_model,
        ]
        return _clean_models(models) or [OPENROUTER_DEFAULT_MODEL]

    @property
    def openrouter_vision_models(self) -> list[str]:
        models = [self.openrouter_vision_model_1, self.openrouter_vision_model_2]
        return _clean_models(models)


def _clean_models(models: list[str | None]) -> list[str]:
    clean_models: list[str] = []
    seen: set[str] = set()
    for model in models:
        if not model:
            continue
        model = OPENROUTER_LEGACY_MODEL_ALIASES.get(model.strip(), model.strip())
        if not model or model in seen:
            continue
        seen.add(model)
        clean_models.append(model)
    return clean_models


@lru_cache
def get_settings() -> Settings:
    return Settings()
