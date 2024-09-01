from dotenv import load_dotenv
import logging


from app.settings import Settings

load_dotenv()

settings = Settings()


app_logger = logging.getLogger('plutus.startup')