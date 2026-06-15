# ABOUTME: App configuration loaded from environment variables.
# ABOUTME: All env vars with defaults; database_url and SMTP creds are required in prod.

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    # Email notifications
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email: str = ""

    # Optional Instagram credentials — improves reliability, avoids rate limits
    instagram_username: str = ""
    instagram_password: str = ""

    # How often to run the timeline check (in hours)
    check_interval_hours: int = 2

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
