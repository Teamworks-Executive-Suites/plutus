from httpx import AsyncClient

import logging
from main import app
from models import Trip, Refund, PropertyCal

from settings import Settings

settings = Settings()

logger = logging.getLogger(__name__)


class PlutusTestCase(
