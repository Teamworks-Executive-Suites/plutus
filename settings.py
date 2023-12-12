from typing import Optional

from pydantic_settings import SettingsConfigDict, BaseSettings


class Settings(BaseSettings):
    # Dev and Testing
    testing: bool = False
    dev: bool = False
    log_level: str = 'INFO'

    logfire_token: Optional[str] = None

    # Firebase Creds




    model_config: SettingsConfigDict(env_file='.env', extra='allow')
