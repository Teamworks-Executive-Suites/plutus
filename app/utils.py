import logging

from dotenv import load_dotenv

from app.settings import Settings

load_dotenv()

settings = Settings()


app_logger = logging.getLogger('plutus.startup')
