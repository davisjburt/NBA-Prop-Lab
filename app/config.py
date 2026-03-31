import os


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    @staticmethod
    def get_database_uri() -> str:
        _load_env_files()
        url = os.environ.get("DATABASE_URL", "sqlite:///prop_lab.db")
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        return url