import json
import os
from datetime import datetime, timezone

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()
tz = timezone.utc

current_time = datetime.now(timezone.utc)

cred = credentials.Certificate(
    json.loads(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
)

app = firebase_admin.initialize_app(cred)
db = firestore.client()