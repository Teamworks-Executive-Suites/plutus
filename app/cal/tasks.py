import uuid
from datetime import datetime, timedelta
from typing import Any, Union

import logfire
from fastapi import HTTPException
from google.cloud.firestore_v1 import FieldFilter
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import ValidationError
from pytz import timezone

from app.cal._utils import app_logger
from app.firebase_setup import current_time, db
from app.models import CancelledGCalEvent, Date, GCalEvent, TripData
from app.utils import settings

creds = service_account.Credentials.from_service_account_info(
    settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
)


def renew_notification_channel(calendar_id, channel_id, channel_type, channel_address):
    service = build('calendar', 'v3', credentials=creds)

    # Log the input parameters
    app_logger.info(
        'Renewing notification channel for calendar_id: %s, channel_id: %s, channel_type: %s, channel_address: %s',
        calendar_id,
        channel_id,
        channel_type,
        channel_address,
    )

    try:
        # Create a new channel with a unique id
        new_channel_id = str(uuid.uuid4())
        new_channel = (
            service.events()
            .watch(
                calendarId=calendar_id, body={'id': new_channel_id, 'type': channel_type, 'address': channel_address}
            )
            .execute()
        )

        app_logger.info(
            'Renewed notification channel. Old id: %s, new id: %s, new expiry: %s',
            channel_id,
            new_channel['id'],
            new_channel.get('expiration'),
        )

        # Ensure the function returns a tuple with two values
        return new_channel, new_channel.get('expiration')
    except HttpError as e:
        app_logger.error('Error renewing notification channel: %s', e)
        raise HTTPException(status_code=500, detail=str(e))


def sync_calendar_events(property_doc_ref: Any, retry_count: int = 0):
    with logfire.span('sync_calendar_events'):
        if isinstance(property_doc_ref, str):
            try:
                property_doc_ref = db.document(property_doc_ref)
            except ValueError:
                app_logger.error('Invalid property document reference: %s', property_doc_ref)
                raise HTTPException(status_code=400, detail='Invalid property document reference')

        try:
            property_doc = property_doc_ref.get()
        except ValueError:
            app_logger.error('Invalid property document reference: %s', property_doc_ref)
            raise HTTPException(status_code=400, detail='Invalid property document reference')

        if not property_doc.exists:
            app_logger.error('Property document does not exist for: %s', property_doc_ref)
            raise HTTPException(status_code=404, detail='Property not found')

        app_logger.info('Syncing calendar for property:%s', property_doc_ref.id)

        property_doc_dict = property_doc.to_dict()
        calendar_id = property_doc_dict.get('externalCalendar')
        if retry_count == 0:
            next_sync_token = property_doc_dict.get('nextSyncToken', '')
        else:
            next_sync_token = ''

        # Call the Google Calendar API to fetch the events
        service = build('calendar', 'v3', credentials=creds)
        page_token = None

        with logfire.span('syncing calendar events with Google Calendar'):
            try:
                while True:
                    events_result = (
                        service.events()
                        .list(calendarId=calendar_id, syncToken=next_sync_token, pageToken=page_token)
                        .execute()
                    )

                    events = events_result.get('items', [])
                    app_logger.info('%s events found in calendar: %s', len(events), calendar_id)
                    for event in events:
                        try:
                            # Validate the event data with the appropriate model
                            if event['status'] == 'cancelled':
                                app_logger.info('Cancelled event: %s', event['id'])
                                validated_event = CancelledGCalEvent.parse_obj(event)
                            else:
                                app_logger.info('Valid event: %s', event['id'])
                                validated_event = GCalEvent.parse_obj(event)
                        except ValidationError as ve:
                            app_logger.error('Event validation error: %s, Event: %s', ve, event)
                            continue

                        # Process each event
                        process_event(validated_event, property_doc_ref)

                    next_sync_token = events_result.get('nextSyncToken')
                    property_doc_ref.update({'nextSyncToken': next_sync_token})

                    page_token = events_result.get('nextPageToken')
                    if not page_token:
                        break
            except HttpError as e:
                if e.resp.status == 410:
                    if retry_count < 2:
                        app_logger.info('Invalid sync token, clearing event store and re-syncing.')
                        clear_event_store(property_doc_ref.path)
                        # Reset the sync token
                        next_sync_token = ''
                        sync_calendar_events(property_doc_ref, retry_count + 1)
                    else:
                        app_logger.error('Error syncing calendar: %s. Maximum retry attempts exceeded.', e)
                        raise HTTPException(status_code=500, detail=str(e))
                else:
                    app_logger.error('Error syncing calendar: %s', e)
                    raise HTTPException(status_code=500, detail=str(e))


def convert_event_to_trip_data(event: GCalEvent, property_doc_ref: Any) -> TripData | None:
    with logfire.span('convert_event_to_trip_data'):
        if 'Buffer Time' in event.summary:
            # Skip the event if it contains 'Buffer Time' in the summary
            app_logger.info('Skipping event with Buffer Time in summary: %s', event.summary)
            return None
        if isinstance(event.start, Date):
            # Fetch the property document
            property_doc = property_doc_ref.get()
            if not property_doc.exists:
                raise ValueError('Property document does not exist')

            # Get the timezone from the property document
            property_timezone = timezone(property_doc.to_dict().get('timezone', 'UTC'))

            if isinstance(event.start, Date):
                # Parse the date and set the time to 00:00:00 in the property's timezone
                start_date = datetime.fromisoformat(event.start.date)
                start_datetime = property_timezone.localize(start_date.replace(hour=0, minute=0, second=0))

                # Parse the date and set the time to 00:00:00 on the next day in the property's timezone
                end_date = datetime.fromisoformat(event.end.date)
                end_datetime = property_timezone.localize(end_date.replace(hour=0, minute=0, second=0))
        else:
            start_datetime_str = event.start.dateTime
            end_datetime_str = event.end.dateTime

            # Parse the start and end datetime strings from the event
            start_datetime = datetime.fromisoformat(start_datetime_str) if start_datetime_str else None
            end_datetime = datetime.fromisoformat(end_datetime_str) if end_datetime_str else None

        app_logger.info('Parsed start datetime: %s', start_datetime)
        app_logger.info('Parsed end datetime: %s', end_datetime)

        if not start_datetime or not end_datetime:
            raise ValueError('Event start or end datetime is missing')

        # If internal event, set isExternal to False
        if 'Teamworks' in event.summary:
            is_external = False
        else:
            is_external = True

        # Creating the TripData instance
        trip_data = TripData(
            tripCreated=current_time,
            isExternal=is_external,
            isInquiry=False,
            propertyRef=property_doc_ref,
            tripBeginDateTime=start_datetime,
            tripDate=start_datetime.replace(hour=0, minute=0, second=0),  # Set tripDate to be at 00:00:00
            tripEndDateTime=end_datetime,
            eventId=event.id,
            eventSummary=event.summary or '',  # Use an empty string if 'summary' is missing
        )

        return trip_data


def process_event(event: Union[GCalEvent, CancelledGCalEvent], property_doc_ref: Any):
    if event.status == 'cancelled':
        handle_cancelled_event(event)
    else:
        handle_validated_event(event, property_doc_ref)


def handle_cancelled_event(event: CancelledGCalEvent):
    existing_trip_ref = db.collection('trips').where(filter=FieldFilter('eventId', '==', event.id)).get()
    if existing_trip_ref:
        existing_trip_ref[0].reference.delete()
        app_logger.info(f'Deleted trip for cancelled event: {event.id}')


def handle_validated_event(event: GCalEvent, property_doc_ref: Any):
    trip_data = convert_event_to_trip_data(event, property_doc_ref)
    if not trip_data:
        app_logger.info('Trip data is None, skipping event: %s', event.id)
        return
    existing_trip_ref = db.collection('trips').where(filter=FieldFilter('eventId', '==', event.id)).get()
    if existing_trip_ref:
        update_existing_trip(existing_trip_ref[0], trip_data, event)
    else:
        create_new_trip(trip_data, event)


def update_existing_trip(trip_ref, trip_data: TripData, event: GCalEvent):
    """
    Update an existing trip in the Firestore database from the Google Calendar event,
    """
    trip_ref.reference.update(trip_data.dict())
    app_logger.info('Updated trip for event: %s, trip ref: %s', event.id, trip_ref.id)


def create_new_trip(trip_data: TripData, event: GCalEvent):
    trip_ref = db.collection('trips').add(trip_data.dict())
    app_logger.info(f'Created new trip for event: {event.id}, trip ref: {trip_ref[1].id}')


def clear_event_store(property_ref: str):
    # Get a reference to the 'trips' collection
    trips_ref = db.collection('trips')

    # Get the current time
    now = datetime.utcnow()

    # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is True,
    # and 'tripBeginDateTime' is in the future
    trips = (
        trips_ref.where(filter=FieldFilter('propertyRef', '==', property_ref))
        .where(filter=FieldFilter('isExternal', '==', True))
        .where(filter=FieldFilter('tripBeginDateTime', '>', now))
        .stream()
    )

    # Delete each document
    for trip in trips:
        trip.reference.delete()

    app_logger.info('Event store successfully cleared.')


def delete_calendar_watch_channel(id: str, resource_id: str):
    app_logger.info('Deleting calendar watch channel: %s', id)
    # Call the Google Calendar API to delete the channel
    service = build('calendar', 'v3', credentials=creds)
    try:
        service.channels().stop(body={'id': id, 'resourceId': resource_id}).execute()
        app_logger.info('Calendar watch channel successfully deleted.')
    except HttpError as e:
        app_logger.error('Error deleting calendar watch channel: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


def initialize_trips_from_cal(property_ref: str, calendar_id: str):
    with logfire.span('initialize_trips_from_cal'):
        app_logger.info('Initialising trips from calendar: %s , property: %s', calendar_id, property_ref)

        # get the property document
        collection_id, document_id = property_ref.split('/')
        property_doc = db.collection(collection_id).document(document_id)

        # Update the externalCalendar field with the provided calendar_id
        property_doc.update({'externalCalendar': calendar_id})

        # Call the Google Calendar API to fetch the future events
        service = build('calendar', 'v3', credentials=creds)

        # test calendar list
        calendars = service.calendarList().list().execute()
        for calendar_list_entry in calendars['items']:
            app_logger.info(calendar_list_entry['id'], calendar_list_entry['summary'])

        # Set up the webhook
        with logfire.span('setting up webhook for calendar'):
            channel_id = property_ref
            app_logger.info('Setting up webhook and setting the channel_id: %s', property_ref)
            webhook_url = f'{settings.url}/cal_webhook?calendar_id={property_ref}'
            new_channel, expiration = renew_notification_channel(calendar_id, channel_id, 'web_hook', webhook_url)

            # Update the property document with the new channel id and expiration time
            property_doc.update({'channelId': new_channel['id'], 'channelExpiration': expiration})

        sync_calendar_events(property_doc)
        create_events_for_future_trips(property_doc.id)


def create_events_for_future_trips(property_doc_id: str):
    with logfire.span(f'create_events_for_future_trips for property: {property_doc_id}'):
        # Get the current time
        now = datetime.utcnow()

        # Fetch the specific property document
        property_doc = db.collection('properties').document(property_doc_id).get()
        if not property_doc.exists:
            app_logger.error('Property document does not exist for: %s', property_doc_id)
            raise HTTPException(status_code=404, detail='Property not found')

        # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is False,
        # 'eventId' does not exist, and 'tripBeginDateTime' is in the future
        future_trips = (
            db.collection('trips')
            .where(filter=FieldFilter('propertyRef', '==', property_doc.reference))
            .where(filter=FieldFilter('isExternal', '==', False))
            .where(filter=FieldFilter('tripBeginDateTime', '>', now))
            .stream()
        )

        if not future_trips:
            app_logger.info('No future trips found for property: %s', property_doc_id)
            return

        # For each future trip, create an event and call create_or_update_event_from_trip
        for trip in future_trips:
            trip_data = trip.to_dict()
            app_logger.info('Trip data: %s', trip)
            if 'eventId' not in trip_data:
                # Call create_or_update_event_from_trip to create the event
                app_logger.info('Creating event for trip: %s', trip.reference)
                document_ref_str = 'properties/' + property_doc_id
                trip_ref_str = 'trips/' + trip.id
                create_or_update_event_from_trip(document_ref_str, trip_ref_str)
            else:
                app_logger.info('Event already exists for trip: %s', trip.reference)


def create_or_update_event_from_trip(property_ref, trip_ref):
    """
    Create or update an event on the Google Calendar associated with the property,
    including buffer time events before and after the main event.
    """
    with logfire.span('create_or_update_event_from_trip'):
        # Fetch the specific property document
        property_collection_id, property_document_id = property_ref.split('/')
        property_doc = db.collection(property_collection_id).document(property_document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for trip: %s', property_ref)
            property_data = property_doc.to_dict()
            calendar_id = property_data['externalCalendar']

            if calendar_id:
                app_logger.info('Calendar ID: %s', calendar_id)
            else:
                app_logger.error('No external calendar set for property: %s', property_ref)
                raise HTTPException(status_code=400, detail='No external calendar set for property')

            property_name = property_data['propertyName']  # Fetch the property name

            # Fetch the specific trip document
            trip_collection_id, trip_document_id = trip_ref.split('/')
            trip_doc = db.collection(trip_collection_id).document(trip_document_id).get()
            if trip_doc.exists:
                trip_data = trip_doc.to_dict()

                # Fetch the specific user document
                app_logger.info('UserRef: %s', trip_data['userRef'].path)
                collection_id, document_id = trip_data['userRef'].path.split('/')
                user_doc = db.collection(collection_id).document(document_id).get()
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    guest_name = user_data['display_name'] or 'Guest'
                    app_logger.info('Guest name: %s', guest_name)

                    # Construct the booking link
                    booking_link = f'{settings.app_url}/bookingDetails?tripPassed={trip_document_id}&property={property_document_id}'

                    # Set the event summary based on whether the trip is blocked or not
                    if trip_doc.get('isBlocked'):
                        summary = 'Blocked | Teamworks'
                        app_logger.info('Blocked event summary: %s', summary)
                    else:
                        summary = f'Office Booking for {guest_name} | Teamworks'

                    # Calculate the buffer times
                    buffer_duration = timedelta(minutes=settings.buffer_time)
                    main_start = trip_data['tripBeginDateTime']
                    main_end = trip_data['tripEndDateTime']
                    buffer_start = main_start - buffer_duration
                    buffer_end = main_end + buffer_duration

                    # Adjust the main event times
                    adjusted_start = main_start
                    adjusted_end = main_end

                    # Create the main event data
                    main_event_data = {
                        'summary': summary,
                        'description': f'Property: {property_name}\nTrip Ref: {trip_ref}\nBooking Link: {booking_link}',
                        'start': {'dateTime': adjusted_start.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': adjusted_end.isoformat(), 'timeZone': 'UTC'},
                    }

                    # Create the buffer events data
                    buffer_before_data = {
                        'summary': f'Buffer Time for {summary}',
                        'start': {'dateTime': buffer_start.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': main_start.isoformat(), 'timeZone': 'UTC'},
                    }
                    buffer_after_data = {
                        'summary': f'Buffer Time for {summary}',
                        'start': {'dateTime': main_end.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': buffer_end.isoformat(), 'timeZone': 'UTC'},
                    }

                    # Call the Google Calendar API to update or create the events
                    service = build('calendar', 'v3', credentials=creds)

                    # Handle the main event
                    if 'eventId' in trip_data:
                        app_logger.info('Updating main event: %s', trip_data['eventId'])
                        main_event_data['id'] = trip_data['eventId']
                        service.events().update(
                            calendarId=calendar_id, eventId=trip_data['eventId'], body=main_event_data
                        ).execute()
                    else:
                        event = service.events().insert(calendarId=calendar_id, body=main_event_data).execute()
                        app_logger.info('Created main event: %s', event['id'])
                        trip_doc.reference.update({'eventId': event['id']})

                    # Create the buffer events
                    app_logger.info('Creating buffer before event')
                    service.events().insert(calendarId=calendar_id, body=buffer_before_data).execute()

                    app_logger.info('Creating buffer after event')
                    service.events().insert(calendarId=calendar_id, body=buffer_after_data).execute()

                else:
                    app_logger.error('User document does not exist for: %s', trip_data['userRef'])
                    raise HttpError
            else:
                app_logger.error('Trip document does not exist for: %s', trip_ref)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError


def delete_event_from_trip(property_ref, trip_ref):
    """
    Delete an event from the Google Calendar associated with the property
    """
    with logfire.span('delete_event_from_trip'):
        app_logger.info('Deleting event from trip: %s , property: %s', trip_ref, property_ref)
        # Fetch the specific property document
        collection_id, document_id = property_ref.split('/')
        property_doc = db.collection(collection_id).document(document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for trip: %s', property_ref)
            property_data = property_doc.to_dict()
            calendar_id = property_data['externalCalendar']

            # Fetch the specific trip document
            collection_id, document_id = trip_ref.split('/')
            trip_doc = db.collection(collection_id).document(document_id).get()
            if trip_doc.exists:
                trip_data = trip_doc.to_dict()

                # Call the Google Calendar API to delete the event
                service = build('calendar', 'v3', credentials=creds)
                service.events().delete(calendarId=calendar_id, eventId=trip_data['eventId']).execute()
            else:
                app_logger.error('Trip document does not exist for: %s', trip_ref)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError


def delete_trip_from_event(property_ref, event_id):
    """
    Delete a trip associated with an event from the Firestore database
    """
    with logfire.span('delete_trip_from_event'):
        app_logger.info('Deleting trip associated with event: %s , property: %s', event_id, property_ref)
        # Fetch the specific property document
        collection_id, document_id = property_ref.split('/')
        property_doc = db.collection(collection_id).document(document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for event: %s', property_ref)

            # Fetch the specific trip document associated with the event id
            trip_ref = db.collection('trips').where(filter=FieldFilter('eventId', '==', event_id)).get()

            if trip_ref:
                # Delete the trip document from Firestore
                trip_ref[0].reference.delete()
                app_logger.info('Trip document successfully deleted: %s', trip_ref[0].id)
            else:
                app_logger.error('Trip document does not exist for event: %s', event_id)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError
