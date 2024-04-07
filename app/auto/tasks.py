import base64

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


def complete_trip_sms(trip_ref: str, property_ref: str):
    # Create the property link
    property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_ref}&property={property_ref}'

    # Get the host phone numbers
    property_doc = db.collection('properties').document(property_ref).get()
    host_doc = db.collection('users').document(property_doc.get('userRef')).get()
    host_number = host_doc.get('phone_number')
    send_sms(host_number, f'Your trip {trip_ref.id} has been completed. View here:{property_link}')

    # Get the guest phone numbers
    trip_doc = db.collection('trips').document(trip_ref).get()
    guest_doc = db.collection('users').document(trip_doc.get('userRef')).get()
    guest_number = guest_doc.get('phone_number')
    send_sms(
        guest_number, f'Your trip {trip_ref.id} has been completed. Please review the host. View here:{property_link}'
    )


def auto_complete():
    """
    Function called every hour, checks if trip is complete and if current
    time is past trip end time.
    """
    with logfire.span('auto_complete'):
        # Iterate through every property
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            # Iterate through every trip in property
            trips = db.collection('trips').where(filter=FieldFilter('propertyRef', '==', prop.reference)).stream()

            for trip in trips:
                if not trip.exists:
                    app_logger.error('Trip document not found for property %s', prop.id)
                    continue  # Changed from return to continue to process the next trip

                if (not trip.get('complete') or trip.get('upcoming')) and (current_time > trip.get('tripEndDateTime')):
                    try:
                        trip.reference.update({'complete': True, 'upcoming': False})
                        app_logger.info('Trip %s for property %s marked as complete', trip.id, prop.id)

                        complete_trip_sms(trip.reference, prop.reference)

                    except Exception as e:
                        app_logger.error('Failed to update trip %s for property %S: %s', trip.id, prop.id, e)

    return True  # Added a return statement for consistency
