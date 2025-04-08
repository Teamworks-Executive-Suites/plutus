from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    testing: bool = False
    dev_mode: bool = False
    log_level: str = 'INFO'
    test_token: str = 'test-token'
    master_token: str = ''
    logfire_token: Optional[str] = None

    url: str = 'http://localhost:8000'
    app_url: str = 'https://app.bookteamworks.com'

    buffer_time: int = 30

    # Google
    g_project_id: str = 'teamworks-3b262'
    g_client_email: str = 'firebase-adminsdk-2xapk@teamworks-3b262.iam.gserviceaccount.com'
    g_private_key_id: str = ''
    g_private_key: str = ''
    g_client_id: str = '107343977696521340350'
    g_auth_uri: str = 'https://accounts.google.com/o/oauth2/auth'
    g_token_uri: str = 'https://oauth2.googleapis.com/token'
    g_auth_provider_x509_cert_url: str = 'https://www.googleapis.com/oauth2/v1/certs'
    g_client_x509_cert_url: str = 'https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-2xapk%40teamworks-3b262.iam.gserviceaccount.com'

    g_calendar_resource_id: str = 'zaI1vco_ZDFf7n_oBTclPGvx6Zk'

    # Twilio
    t_account_sid: str = ''
    t_auth_token: str = ''
    t_from_number: str = ''
    t_messaging_service_sid: str = ''


    platform_user_id: str = 'ovd8KQBXVpdw1n0H3AXlKN7AHDr2'
    # Firebase Creds
    @property
    def firebase_credentials(self):
        return {
            'type': 'service_account',
            'project_id': self.g_project_id,
            'private_key_id': self.g_private_key_id,
            'private_key': self.g_private_key.replace('\\n', '\n'),
            'client_email': self.g_client_email,
            'client_id': self.g_client_id,
            'auth_uri': self.g_auth_uri,
            'token_uri': self.g_token_uri,
            'auth_provider_x509_cert_url': self.g_auth_provider_x509_cert_url,
            'client_x509_cert_url': self.g_client_x509_cert_url,
        }

    model_config = SettingsConfigDict(env_file='.env', extra='allow')
