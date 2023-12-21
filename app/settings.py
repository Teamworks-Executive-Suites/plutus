from typing import Optional

from pydantic_settings import SettingsConfigDict, BaseSettings


class Settings(BaseSettings):
    # Dev and Testing
    testing: bool = False
    dev: bool = False
    log_level: str = 'INFO'
    test_token: str = '29326669-224b-414c-9978-39e1cd8c194c'

    logfire_token: Optional[str] = None

    # Firebase Creds




    model_config: SettingsConfigDict(env_file='../.env', extra='allow')
