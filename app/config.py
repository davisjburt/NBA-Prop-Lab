import os


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def database_uri() -> str:
    """DATABASE_URL from env (and optional .env); Render uses postgres:// which SQLAlchemy expects as postgresql://."""
    _load_env_files()
    url = os.environ.get("DATABASE_URL", "sqlite:///prop_lab.db")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
