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

    # UTC hour (0-23) to run the daily check
    check_hour: int = 9

    class Config:
        env_file = ".env"


settings = Settings()
