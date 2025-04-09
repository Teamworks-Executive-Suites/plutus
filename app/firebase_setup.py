import asyncio
import logging
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore, remote_config
from mockfirestore import MockFirestore

from app.utils import app_logger, settings

tz = timezone.utc

current_time = datetime.now(timezone.utc)

cred = credentials.Certificate(settings.firebase_credentials)

app = firebase_admin.initialize_app(cred)

default_config = {
    'CloudVersion': 'v1.0.4',
    'hostFee': '0.15',
    'guestFee': '0.05',
}

template = remote_config.init_server_template(app, default_config)

# load the template
asyncio.run(template.load())

# Add template parameters to config
config = template.evaluate()

if config:
    CLOUD_VERSION = config.get_string('CloudVersion')
    HOST_FEE = config.get_float('hostFee')
    GUEST_FEE = config.get_float('guestFee')

    app_logger.info(f'Cloud Version: {CLOUD_VERSION}')
    app_logger.info(f'Host Fee: {HOST_FEE}')
    app_logger.info(f'Guest Fee: {GUEST_FEE}')
else:
    app_logger.error('Failed to retrieve remote config values.')

MOCK_DB = MockFirestore()

if settings.testing:
    logging.info('Using mock db')
    db = MOCK_DB
else:
    db = firestore.client()
