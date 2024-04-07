import uuid
from datetime import datetime, timedelta

import logfire
from devtools import debug
from fastapi import HTTPException
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.cal._utils import app_logger
from app.firebase_setup import db
from app.models import TripData
from app.utils import settings

creds = service_account.Credentials.from_service_account_info(
    settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
)


def delete_calendar_watch_channel(channel_id, resource_id):
    app_logger.info('Deleting calendar watch channel: %s', channel_id)
    # Call the Google Calendar API to delete the channel
    service = build('calendar', 'v3', credentials=creds)
    try:
        service.channels().stop(body={'id': channel_id, 'resourceId': resource_id}).execute()
        app_logger.info('Calendar watch channel successfully deleted.')
    except HttpError as e:
        app_logger.error('Error deleting calendar watch channel: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


def create_or_update_trip_from_event(calendar_id, event):
    app_logger.info('Creating or updating trip from event: %s', event['id'])
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
        app_logger.info('Trip document exists for event: %s', trip_ref.id)
        # The trip document exists, so update it
        trip_ref.update(trip_data)
    else:
        app_logger.info('Trip document does not exist for event, so we create it: %s', event['id'])
        # The trip document does not exist, so create it
        db.collection('trips').add(trip_data)


def initalize_trips_from_cal(property_ref, calendar_id):
    app_logger.info('Initialising trips from calendar: %s , property: %s', calendar_id, property_ref)

    # get the property document
    collection_id, document_id = property_ref.split('/')
    property_doc_ref = db.collection(collection_id).document(document_id)

    # Call the Google Calendar API to fetch the future events
    service = build('calendar', 'v3', credentials=creds)
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time

    # test calendar list
    calendars = service.calendarList().list().execute()
    debug(calendars)
    for calendar_list_entry in calendars['items']:
        app_logger.info(calendar_list_entry['id'], calendar_list_entry['summary'])

    # Set up the webhook
    with logfire.span('setting up webhook for calendar'):
        channel_id = str(uuid.uuid4())
        app_logger.info('Setting up webhook and setting the channel_id: %s', channel_id)
        webhook_url = f'{settings.url}/cal_webhook?calendar_id={calendar_id}'
        channel = (
            service.events()
            .watch(calendarId=calendar_id, body={'id': channel_id, 'type': 'web_hook', 'address': webhook_url})
            .execute()
        )

        property_doc_ref.update({'channelId': channel['resourceId']})

    with logfire.span('fetching events from calendar'):
        page_token = None
        while True:
            events_result = (
                service.events()
                .list(calendarId=calendar_id, timeMin=now, singleEvents=True, orderBy='startTime', pageToken=page_token)
                .execute()
            )
            events = events_result.get('items', [])

            # For each event, create a trip document
            for event in events:
                debug(event)

                # Convert the event data to Firestore trip format
                trip_data = TripData(
                    isExternal=True,
                    propertyRef=property_ref,
                    tripBeginDateTime=datetime.fromisoformat(event['start'].get('dateTime')),
                    tripEndDateTime=datetime.fromisoformat(event['end'].get('dateTime')),
                    eventId=event['id'],  # Save the event ID on the trip
                )

                # Convert the trip_data to a dictionary
                trip_data_dict = trip_data.dict()

                # Add the trip to Firestore
                db.collection('trips').add(trip_data_dict)
                app_logger.info('Added trip from event: %s', event['id'])

            page_token = events_result.get('nextPageToken')
            if not page_token:
                break


def create_or_update_event_from_trip(property_ref, trip_ref):
    app_logger.info('Creating or updating event from trip: %s , property: %s', trip_ref, property_ref)
    # Fetch the specific property document

    collection_id, document_id = property_ref.split('/')
    property_doc = db.collection(collection_id).document(document_id).get()

    if property_doc.exists:
        app_logger.info('Property document exists for trip: %s', property_ref)
        property_data = property_doc.to_dict()
        calendar_id = property_data['externalCalendar']
        property_name = property_data['propertyName']  # Fetch the property name

        # Fetch the specific trip document
        collection_id, document_id = trip_ref.split('/')
        trip_doc = db.collection(collection_id).document(document_id).get()
        if trip_doc.exists:
            trip_data = trip_doc.to_dict()

            # Fetch the specific user document
            collection_id, document_id = trip_data['userRef'].split('/')
            user_doc = db.collection(collection_id).document(document_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                guest_name = user_data['displayName']

                # Construct the booking link
                booking_link = (
                    f'https://app.bookteamworks.com/tripDetails?tripPassed={trip_ref}&property={property_ref}'
                )

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
                    app_logger.info('Updating event: %s', trip_data['eventId'])
                    service.events().update(
                        calendarId=calendar_id, eventId=trip_data['eventId'], body=event_data
                    ).execute()
                else:
                    app_logger.info('Creating a new event')
                    service.events().insert(calendarId=calendar_id, body=event_data).execute()

            else:
                app_logger.error('User document does not exist for: %s', trip_data['userRef'])
                raise HttpError
        else:
            app_logger.error('Trip document does not exist for: %s', trip_ref)
            raise HttpError
    else:
        app_logger.error('Property document does not exist for: %s', property_ref)
        raise HttpError
