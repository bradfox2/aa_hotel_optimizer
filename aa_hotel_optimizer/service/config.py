from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LP_", env_file=".env", extra="ignore")
    environment: str = "development"
    public_url: str = "http://127.0.0.1:8787"
    database_url: str = "sqlite:///.local/optimizer.sqlite3"
    app_name: str = "LP Optimizer"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    smtp_starttls: bool = True
    resend_api_key: str = ""
    beta_emails: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    stripe_trip_pass_price_id: str = ""
    live_billing_enabled: bool = False
    plan_label: str = "Membership"
    plan_price_label: str = "$19/month"
    trip_pass_price_label: str = "$9"
    trip_pass_searches: int = Field(default=20, ge=1, le=1000)
    free_searches: int = Field(default=2, ge=0, le=100)
    paid_searches_per_month: int = Field(default=100, ge=1, le=10000)
    companion_url: str = ""
    max_provider_calls: int = Field(default=1000, ge=1, le=5000)
    provider_enabled: bool = False
    session_days: int = Field(default=30, ge=1, le=90)

    @field_validator("database_url")
    @classmethod
    def postgres_driver(cls, value):
        # Managed hosts commonly supply a URL without an explicit psycopg driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def production(self):
        return self.environment in ("staging", "production")

    @property
    def email_enabled(self):
        return bool(self.email_from and (self.resend_api_key or self.smtp_host))

    @property
    def test_billing(self):
        return self.stripe_secret_key.startswith(("sk_test_", "rk_test_"))

    @property
    def billing_enabled(self):
        configured = bool(
            self.stripe_secret_key
            and self.stripe_price_id
            and self.stripe_trip_pass_price_id
            and self.stripe_webhook_secret
        )
        live_ready = (
            self.environment == "production"
            and self.live_billing_enabled
            and self.provider_enabled
            and self.companion_url.startswith("https://chromewebstore.google.com/detail/")
        )
        return configured and (self.test_billing or live_ready)

    def validate_deployment(self):
        if self.environment not in ("development", "staging", "production"):
            raise ValueError("LP_ENVIRONMENT must be development, staging, or production.")
        parsed = urlparse(self.public_url)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.scheme not in ("http", "https")
        ):
            raise ValueError("LP_PUBLIC_URL must be a valid HTTP(S) origin without credentials.")
        self.public_url = self.public_url.rstrip("/")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("LP_PUBLIC_URL must be an origin without a path, query or fragment.")
        if self.production:
            if parsed.scheme != "https":
                raise ValueError("Production requires an HTTPS public URL.")
            if self.environment == "production" and not self.email_enabled:
                raise ValueError("Production requires email delivery for sign-in links.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Use PostgreSQL and migrations for production.")
        elif parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Development login is limited to a loopback public URL.")


@lru_cache
def settings():
    return Settings()
