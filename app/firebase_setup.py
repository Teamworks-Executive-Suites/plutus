import logging
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from mockfirestore import MockFirestore

from app.utils import settings

tz = timezone.utc


def utc_now():
    """The current UTC time, read at the moment of the call.

    This was a module-level `current_time = datetime.now(timezone.utc)`. Evaluated once
    at import, it froze at deploy time inside a long-lived uvicorn process, so every
    createdAt/processedAt written to the ledger carried the process start time rather
    than the write time, and the cancellation refund window computed every booking as
    further away than it really was — over-refunding by a whole tier once a deploy had
    been up long enough.
    """
    return datetime.now(timezone.utc)


cred = credentials.Certificate(settings.firebase_credentials)

app = firebase_admin.initialize_app(cred)

MOCK_DB = MockFirestore()

if settings.testing:
    logging.info('Using mock db')
    db = MOCK_DB
else:
    db = firestore.client()
