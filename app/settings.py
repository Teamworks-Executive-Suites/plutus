from typing import Optional

from pydantic_settings import SettingsConfigDict, BaseSettings


class Settings(BaseSettings):
    # Dev and Testing
    testing: bool = False
    dev: bool = False
    log_level: str = 'INFO'
    test_token: str = '29326669-224b-414c-9978-39e1cd8c194c'

    logfire_token: Optional[str] = None


    # Google
    g_project_id: str = 'teamworks-3b262'
    g_client_email: str = 'firebase-adminsdk-2xapk@teamworks-3b262.iam.gserviceaccount.com'
    g_private_key_id: str = ''
    g_private_key: str = ''
    g_client_id: str = '107343977696521340350'
    g_auth_uri: str = 'https://accounts.google.com/o/oauth2/auth'
    g_token_uri: str = 'https://oauth2.googleapis.com/token'
    g_auth_provider_x509_cert_url: str = 'https://www.googleapis.com/oauth2/v1/certs'
    g_client_x509_cert_url: str = (
        'https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-2xapk%40teamworks-3b262.iam.gserviceaccount.com'
    )

    # Firebase Creds
    @property
    def firebase_credentials(self):
        return {
            "type": "service_account",
            "project_id": self.g_project_id,
            "private_key_id": self.g_private_key_id,
            "private_key": self.g_private_key,
            "client_email": self.g_client_email,
            "client_id": self.g_client_id,
            "auth_uri": self.g_auth_uri,
            "token_uri": self.g_token_uri,
            "auth_provider_x509_cert_url": self.g_auth_provider_x509_cert_url,
            "client_x509_cert_url": self.g_client_x509_cert_url,
            "universe_domain": "googleapis.com",
        }



    model_config: SettingsConfigDict(env_file='../.env', extra='allow')
