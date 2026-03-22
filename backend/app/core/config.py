import os
from pydantic_settings import BaseSettings
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"

class Settings(BaseSettings):
    MODEL: str = "ollama/qwen3:8b"
    API_BASE: str = "http://localhost:11434"

    ROOT_FOLDER: Path = BACKEND_DIR / "storage"
    DB_PATH: Path = BACKEND_DIR / "data" / "assistant.db"
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_PATH}"

    class Config:
        env_file = ROOT_DIR / ".env"
        env_file_encoding = 'utf-8'

settings = Settings()

settings.ROOT_FOLDER.mkdir(parents=True, exist_ok=True)
settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)