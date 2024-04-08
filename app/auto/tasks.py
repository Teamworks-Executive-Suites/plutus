import base64
import json
from datetime import timedelta

import logfire
import requests

from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db
from app.utils import settings


def send_sms(to: str, body: str):
    """
    Function to send an SMS to a phone number using Twilio API.
    """
    with logfire.span('send_sms'):
        # Twilio API URL
        url = f'https://api.twilio.com/2010-04-01/Accounts/{settings.t_account_sid}/Messages'

        # Twilio Account SID and Auth Token
        account_sid = settings.t_account_sid
        auth_token = settings.t_auth_token

        # Base64 encode the Account SID and Auth Token
        credentials = base64.b64encode(f'{account_sid}:{auth_token}'.encode('utf-8')).decode('utf-8')

        # Headers for the request
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {credentials}'}

        # Data for the request
        data = {
            'To': to,
            'Body': body,
            'From': settings.t_from_number,
            'MessagingServicesSid': settings.t_messaging_service_sid,
        }

        # Send the request
        response = requests.post(url, headers=headers, data=data)

        # Log the response
        app_logger.info('SMS sent to %s: %s', to, body)
        app_logger.info('Response: %s', response.text)


def get_contact_details(trip_ref: str, property_ref: str):
    # Get the host phone numbers
    property_doc = db.collection('properties').document(property_ref).get()
    if not property_doc.exists:
        app_logger.error('Property document does not exist for: %s', property_ref)
        return None, None

    host_doc = db.collection('users').document(property_doc.get('userRef')).get()
    if not host_doc.exists:
        app_logger.error('Host document does not exist for: %s', property_doc.get('userRef'))
        return None, None

    host_number = host_doc.get('phone_number')

    # Get the guest phone numbers
    trip_doc = db.collection('trips').document(trip_ref).get()
    if not trip_doc.exists:
        app_logger.error('Trip document does not exist for: %s', trip_ref)
        return None, None

    guest_doc = db.collection('users').document(trip_doc.get('userRef')).get()
    if not guest_doc.exists:
        app_logger.error('Guest document does not exist for: %s', trip_doc.get('userRef'))
        return None, None

    guest_number = guest_doc.get('phone_number')
    return host_number, guest_number


def complete_trip_sms(trip_ref: str, property_ref: str):
    host_number, guest_number = get_contact_details(trip_ref, property_ref)
    if host_number and guest_number:
        property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_ref}&property={property_ref}'
        send_sms(host_number, f'Your trip {trip_ref} has been completed. View here: {property_link}')
        send_sms(
            guest_number,
            f'Your trip {trip_ref} has been completed🙃. Please review the host. View here: {property_link}',
        )


def send_reminder_sms(trip_ref: str, property_ref: str, time: int):
    host_number, guest_number = get_contact_details(trip_ref, property_ref)
    if host_number and guest_number:
        property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_ref}&property={property_ref}'

        # Send SMS to host and guest
        send_sms(host_number, f'Reminder: Your booking {trip_ref} starts in {time} hours. View here: {property_link}')
        send_sms(guest_number, f'Reminder: Your booking {trip_ref} starts in {time} hours. View here: {property_link}')


def auto_complete_and_notify():
    """
    Function to automatically mark trips as complete and send reminder SMS to the host and guest.
    """
    with logfire.span('auto_complete_and_notify'):
        # Iterate through every property
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            # Iterate through every trip in property

            with logfire.span(f'Processing property: {prop.id}'):

                trips = db.collection('trips').where(filter=FieldFilter('propertyRef', '==', prop.reference)).stream()

                for trip in trips:

                    with logfire.span(f'Processing trip: {trip.id}'):

                        app_logger.info('Trip data: %s', str(trip.to_dict()))

                        if not trip.exists:
                            app_logger.error('Trip document not found for property %s', prop.id)
                            continue
                        app_logger.info('Processing trip %s', trip.id)
                        app_logger.info('Trip data: %s', str(trip.to_dict()))

                        if not trip.exists:
                            app_logger.error('Trip document not found for property %s', prop.id)
                            continue  # Changed from return to continue to process the next trip

                        if (not trip.get('complete') or trip.get('upcoming')) and (
                                current_time > trip.get('tripEndDateTime')):
                            try:
                                trip.reference.update({'complete': True, 'upcoming': False})
                                app_logger.info('Trip %s for property %s marked as complete', trip.id, prop.id)

                                complete_trip_sms(trip.reference, prop.reference)

                            except Exception as e:
                                app_logger.error('Failed to update trip %s for property %S: %s', trip.id, prop.id, e)

                        # Check if current time is one day before the start time of the trip
                        if trip.get('upcoming') and (
                                current_time > (trip.get('tripBeginDateTime') - timedelta(hours=24))):
                            try:
                                send_reminder_sms(trip.reference, prop.reference, 24)

                            except Exception as e:
                                app_logger.error(
                                    'Failed to send reminder SMS for trip %s for property %S: %s', trip.id, prop.id, e
                                )

                        # Check if current time is one hour before the start time of the trip
                        if trip.get('upcoming') and (current_time > trip.get('tripBeginDateTime') + timedelta(hours=1)):
                            try:
                                send_reminder_sms(trip.reference, prop.reference, 1)

                            except Exception as e:
                                app_logger.error(
                                    'Failed to send reminder SMS for trip %s for property %S: %s', trip.id, prop.id, e
                                )
                        else:
                            app_logger.info('No trips to action on for property %s', prop.id)

    return True  # Added a return statement for consistency
