
import logging
from main import app
from models import Trip, Refund, PropertyCal
from fastapi import FastAPI
from fastapi.testclient import TestClient

from settings import Settings

settings = Settings()

logger = logging.getLogger(__name__)



