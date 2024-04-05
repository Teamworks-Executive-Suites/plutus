import os
import pickle
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.cloud.firestore_v1 import FieldFilter
from googleapiclient.errors import HttpError

from app.utils import settings
from app.firebase_setup import db, cred


def create_or_update_trip_from_event(calendar_id, event):
    # Convert the event data to Firestore trip format
    trip_data = {
        'isExternal': True,
        'propertyRef': calendar_id,
        'tripBeginDateTime': datetime.fromisoformat(event['start'].get('dateTime')),
        'tripEndDateTime': datetime.fromisoformat(event['end'].get('dateTime')),
        'eventId': event['id'],  # Save the event ID on the trip
    }

    # Fetch the specific trip document associated with the event id
    trip_ref = db.collection('trips').document(event['id']).get()
    if trip_ref.exists:
        # The trip document exists, so update it
        trip_ref.update(trip_data)
    else:
        # The trip document does not exist, so create it
        db.collection('trips').add(trip_data)


def initalise_trips_from_cal(property_ref, calendar_id):
    # Fetch the property document from Firestore
    collection_id, document_id = property_ref.split('/')
    property_ref = db.collection(collection_id).document(document_id).get()

    # Call the Google Calendar API to fetch the future events
    service = build('calendar', 'v3', credentials=cred)
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time

    # Set up the webhook
    channel_id = property_ref
    webhook_url = f'{settings.url}/cal_webhook?calendar_id={calendar_id}'
    service.events().watch(calendarId=calendar_id, body={
        'id': channel_id,
        'type': 'web_hook',
        'address': webhook_url
    }).execute()

    page_token = None
    while True:
        events_result = service.events().list(calendarId=calendar_id, timeMin=now, singleEvents=True,
                                              orderBy='startTime', pageToken=page_token).execute()
        events = events_result.get('items', [])

        # For each event, create a trip document
        for event in events:
            # Convert the event data to Firestore trip format
            trip_data = {
                'isExternal': True,
                'propertyRef': property_ref.reference,
                'tripBeginDateTime': datetime.fromisoformat(event['start'].get('dateTime')),
                'tripEndDateTime': datetime.fromisoformat(event['end'].get('dateTime')),
                'eventId': event['id'],  # Save the event ID on the trip
            }

            # Add the trip to Firestore
            db.collection('trips').add(trip_data)

        page_token = events_result.get('nextPageToken')
        if not page_token:
            break


def create_or_update_trip_from_event(calendar_id, event):
    # Convert the event data to Firestore trip format
    trip_data = {
        'isExternal': True,
        'propertyRef': calendar_id,
        'tripBeginDateTime': datetime.fromisoformat(event['start'].get('dateTime')),
        'tripEndDateTime': datetime.fromisoformat(event['end'].get('dateTime')),
        'eventId': event.id,  # Save the event ID on the trip
    }

    # Fetch the specific trip document associated with the event id
    trip_ref = db.collection('trips').document(event.id)

    if trip_ref.get().exists:
        # The trip document exists, so update it
        trip_ref.update(trip_data)
    else:
        # The trip document does not exist, so create it
        trip_ref.set(trip_data)
