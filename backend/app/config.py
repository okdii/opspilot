import base64
import sys
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Database
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "opspilot"
    postgres_user: str = "opspilot"
    postgres_password: str
    opspilot_writer_password: str

    # Secrets
    opspilot_jwt_secret: str
    opspilot_encryption_key: str

    # Optional
    opspilot_base_url: str = ""
    debug: bool = False

    @field_validator("opspilot_jwt_secret")
    @classmethod
    def jwt_secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("OPSPILOT_JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("opspilot_encryption_key")
    @classmethod
    def encryption_key_valid(cls, v: str) -> str:
        try:
            decoded = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("OPSPILOT_ENCRYPTION_KEY must be valid base64")
        if len(decoded) != 32:
            raise ValueError("OPSPILOT_ENCRYPTION_KEY must decode to exactly 32 bytes (256 bits)")
        return v

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _load_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:
        print(f"FATAL: Configuration error — {e}", file=sys.stderr)
        print("Generate secrets with:", file=sys.stderr)
        print("  OPSPILOT_JWT_SECRET:       openssl rand -hex 32", file=sys.stderr)
        print("  OPSPILOT_ENCRYPTION_KEY:   openssl rand -base64 32", file=sys.stderr)
        sys.exit(1)


settings = _load_settings()
