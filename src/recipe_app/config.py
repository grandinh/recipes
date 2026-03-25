from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: Path = Path("/root/recipes/data/recipes.db")
    api_host: str = "127.0.0.1"
    api_port: int = 8420
    max_photo_size: int = 10_485_760  # 10MB
    max_response_size: int = 5_242_880  # 5MB for URL fetch
    http_timeout: int = 10

    model_config = {"env_prefix": "RECIPE_"}


settings = Settings()
