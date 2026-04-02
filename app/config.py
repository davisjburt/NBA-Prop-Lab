import os
from pathlib import Path

from sqlalchemy.engine.url import URL, make_url

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """Load repo `.env` first; `override=True` so empty shell exports don't mask `.env`."""
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parent.parent
        load_dotenv(root / ".env", override=True)
        load_dotenv()  # optional cwd `.env`, does not override already-set keys
    except ImportError:
        pass


def _normalize_sqlite_uri(url: str) -> str:
    """Resolve relative sqlite paths to the project root and create parent dirs."""
    if not url.startswith("sqlite:"):
        return url
    u = make_url(url)
    db = u.database
    if db is None or db == ":memory:" or (
        isinstance(db, str) and db.startswith(":memory")
    ):
        return url
    db_path = Path(db)
    if not db_path.is_absolute():
        db_path = (_PROJECT_ROOT / db_path).resolve()
    else:
        db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return URL.create(drivername="sqlite", database=str(db_path)).render_as_string(
        hide_password=False
    )


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    @staticmethod
    def get_database_uri() -> str:
        load_env()
        # Empty DATABASE_URL in .env is truthy as "" and breaks SQLAlchemy — treat as unset.
        for key in ("DATABASE_URL", "LOCAL_DATABASE_URL", "HEROKU_DATABASE_URL"):
            raw = os.environ.get(key)
            if raw and str(raw).strip():
                url = str(raw).strip()
                break
        else:
            url = "sqlite:///prop_lab.db"

        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        return _normalize_sqlite_uri(url)