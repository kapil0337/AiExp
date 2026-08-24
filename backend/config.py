"""Settings, read once from the environment (.env supported for local dev)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Bloom Budget"
    default_currency: str = "INR"

    database_url: str = "sqlite:///./data/bloom.db"

    # NVIDIA NIM (OpenAI-compatible). Blank key -> offline canned sass.
    nvidia_api_key: str = ""
    # 8b answers in ~1s. The 3.3-70b endpoint currently hangs (never returns
    # headers) on this account tier, and 3.1-70b takes ~13s — too slow for a
    # UI bubble. Verified 2026-08-24.
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Google Sign-In ─────────────────────────────────────────────
    google_client_id: str = ""
    allowed_emails: str = ""  # comma-separated, checked case-insensitively
    session_secret: str = ""
    session_cookie_secure: bool = True
    session_max_age_days: int = 30

    @property
    def ai_enabled(self) -> bool:
        return bool(self.nvidia_api_key.strip())

    @property
    def allowed_emails_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def auth_configured(self) -> bool:
        return bool(
            self.google_client_id and self.session_secret and self.allowed_emails_set
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
