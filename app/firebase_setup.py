import logging
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from mockfirestore import MockFirestore


from app.utils import settings

tz = timezone.utc

current_time = datetime.now(timezone.utc)

cred = credentials.Certificate(
    settings.firebase_credentials
)

app = firebase_admin.initialize_app(cred)


MOCK_DB = MockFirestore()


if settings.testing:
    logging.info("Using mock db")
    db = MOCK_DB
else:
    db = firestore.client()