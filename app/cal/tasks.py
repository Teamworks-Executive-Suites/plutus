from datetime import datetime

import logfire
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import timedelta
from googleapiclient.errors import HttpError

from app.cal._utils import app_logger
from app.models import TripData
from app.utils import settings
from app.firebase_setup import db


creds = service_account.Credentials.from_service_account_info(
            settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
        ).with_subject('plutus_google_cal')


def create_or_update_trip_from_event(calendar_id, event):
    app_logger.info(f'Creating or updating trip from event: {event["id"]}')
    # Convert the event data to Firestore trip format
    trip_data = TripData(
        isExternal=True,
        propertyRef=calendar_id,
        tripBeginDateTime=datetime.fromisoformat(event['start'].get('dateTime')),
        tripEndDateTime=datetime.fromisoformat(event['end'].get('dateTime')),
        eventId=event['id'],  # Save the event ID on the trip
    )

    # Fetch the specific trip document associated with the event id
    trip_ref = db.collection('trips').document(event['id']).get()
    if trip_ref.exists:
        app_logger.info(f'Trip document exists for event: {trip_ref.id}')
        # The trip document exists, so update it
        trip_ref.update(trip_data)
    else:
        app_logger.info(f'Trip document does not exist for event, so we create it: {event["id"]}')
        # The trip document does not exist, so create it
        db.collection('trips').add(trip_data)


def initalize_trips_from_cal(property_ref, calendar_id):
    app_logger.info(f'Initialising trips from calendar: {calendar_id}, property: {property_ref}')
    # Fetch the property document from Firestore
    collection_id, document_id = property_ref.split('/')
    property_doc = db.collection(collection_id).document(document_id).get()

    # Call the Google Calendar API to fetch the future events
    service = build('calendar', 'v3', credentials=creds)
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time

    # Set up the webhook
    with logfire.span('setting up webhook for calendar'):
        channel_id = property_doc.get('externalCalendar')
        webhook_url = f'{settings.url}/cal_webhook?calendar_id={calendar_id}'
        service.events().watch(calendarId=calendar_id, body={
            'id': channel_id,
            'type': 'web_hook',
            'address': webhook_url
        }).execute()

    with logfire.span('fetching events from calendar'):
        page_token = None
        while True:
            events_result = service.events().list(calendarId=calendar_id, timeMin=now, singleEvents=True,
                                                  orderBy='startTime', pageToken=page_token).execute()
            events = events_result.get('items', [])

            # For each event, create a trip document
            for event in events:
                # Convert the event data to Firestore trip format
                trip_data = TripData(
                    isExternal=True,
                    propertyRef=property_ref,
                    tripBeginDateTime=datetime.fromisoformat(event['start'].get('dateTime')),
                    tripEndDateTime=datetime.fromisoformat(event['end'].get('dateTime')),
                    eventId=event['id'],  # Save the event ID on the trip
                )

                # Add the trip to Firestore
                db.collection('trips').add(trip_data)
                app_logger.info(f'Added trip from event: {event["id"]}')

            page_token = events_result.get('nextPageToken')
            if not page_token:
                break


def create_or_update_event_from_trip(property_ref, trip_ref):
    app_logger.info(f'Creating or updating event from trip: {trip_ref}, property: {property_ref}')
    # Fetch the specific property document
    property_doc = db.collection('properties').document(property_ref).get()
    if property_doc.exists:
        app_logger.info(f'Property document exists for trip: {property_ref}')
        property_data = property_doc.to_dict()
        calendar_id = property_data['externalCalendar']
        property_name = property_data['propertyName']  # Fetch the property name

        # Fetch the specific trip document
        trip_doc = db.collection('trips').document(trip_ref).get()
        if trip_doc.exists:
            trip_data = trip_doc.to_dict()

            # Fetch the specific user document
            user_doc = db.collection('users').document(trip_data['userRef']).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                guest_name = user_data['displayName']

                # Construct the booking link
                booking_link = f"https://app.bookteamworks.com/tripDetails?tripPassed={trip_ref}&property={property_ref}"

                # Convert the trip data to Google Calendar event format
                # Add 30-minute buffer time to either side of the event
                event_data = {
                    'id': trip_data['eventId'],
                    'summary': f'TW - Office Booking for {guest_name}',  # Generate the event name
                    'description': f'Property: {property_name}\nTrip Ref: {trip_ref}\nBooking Link: {booking_link}',
                    # Add the event description
                    'start': {
                        'dateTime': (trip_data['tripBeginDateTime'] - timedelta(minutes=30)).isoformat(),
                        'timeZone': 'UTC',
                    },
                    'end': {
                        'dateTime': (trip_data['tripEndDateTime'] + timedelta(minutes=30)).isoformat(),
                        'timeZone': 'UTC',
                    },
                }

                # Call the Google Calendar API to update or create the event
                service = build('calendar', 'v3', credentials=creds)
                if 'eventId' in trip_data:
                    app_logger.info(f'Updating event: {trip_data["eventId"]}')
                    service.events().update(calendarId=calendar_id, eventId=trip_data['eventId'],
                                            body=event_data).execute()
                else:
                    app_logger.info('Creating a new event')
                    service.events().insert(calendarId=calendar_id, body=event_data).execute()

            else:
                app_logger.error(f'User document does not exist for: {trip_data["userRef"]}')
                raise HttpError
        else:
            app_logger.error(f'Trip document does not exist for: {trip_ref}')
            raise HttpError
    else:
        app_logger.error(f'Property document does not exist for: {property_ref}')
        raise HttpError
