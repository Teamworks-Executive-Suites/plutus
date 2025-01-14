import base64
from datetime import timedelta

import logfire
import requests
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db
from app.utils import settings


def get_contact_details(trip_ref: str, property_ref: str):
    with logfire.span('get_contact_details'):
        # Get the host phone numbers
        property_doc = db.collection('properties').document(property_ref).get()
        if not property_doc.exists:
            app_logger.error('Property document does not exist for: %s', property_ref)
            return None, None

        host_doc = db.collection('users').document(property_doc.get('userRef')).get()
        if not host_doc.exists:
            app_logger.error('Host document does not exist for: %s', property_doc.get('userRef'))
            return None, None

        if host_doc.get('smsOptIn'):
            host_numbers = host_doc.get('phone_numbers')
        else:
            host_numbers = None

        # Get the guest phone numbers
        trip_doc = db.collection('trips').document(trip_ref).get()
        if not trip_doc.exists:
            app_logger.error('Trip document does not exist for: %s', trip_ref)
            return None, None

        guest_doc = db.collection('users').document(trip_doc.get('userRef')).get()
        if not guest_doc.exists:
            app_logger.error('Guest document does not exist for: %s', trip_doc.get('userRef'))
            return None, None

        if guest_doc.get('smsOptIn'):
            guest_number = guest_doc.get('phone_numbers')[0]
        else:
            guest_number = None

        return host_numbers, guest_number


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


def complete_trip_sms(trip_doc_id: str, property_doc_id: str):
    with logfire.span('complete_trip_sms'):
        host_numbers, guest_number = get_contact_details(trip_doc_id, property_doc_id)
        property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_doc_id}&property={property_doc_id}'

        if host_numbers:
            for host_num in host_numbers:
                send_sms(host_num, f'Your trip {trip_doc_id} has been completed. View here: {property_link}')

        if guest_number:
            send_sms(
                guest_number, f'Your trip {trip_doc_id} has been completed. Please review the host. View here: {property_link}'
            )


def send_reminder_sms(trip_ref: str, property_ref: str, time: int):
    host_numbers, guest_number = get_contact_details(trip_ref, property_ref)
    property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_ref}&property={property_ref}'

    # Send SMS to host and guest
    if guest_number:
        send_sms(guest_number, f'Reminder: Your booking {trip_ref} starts in {time} hours. View here: {property_link}')

    if host_numbers:
        for host_num in host_numbers:
            send_sms(host_num, f'Reminder: Your booking {trip_ref} starts in {time} hours. View here: {property_link}')


def sendgrid_email(trip_doc: dict, property_doc: dict, template_id: str, time: int = None, to_host: bool = False):
    """
    Function to send an email using SendGrid API.
    """
    with logfire.span('sendgrid_email'):
        # SendGrid API URL
        url = 'https://api.sendgrid.com/v3/mail/send'

        # SendGrid API Key
        api_key = settings.sendgrid_api_key

        # Headers for the request
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }

        # Host Doc
        host_doc = db.collection('users').document(property_doc.get('userRef')).get()

        # Guest Doc
        guest_doc = db.collection('users').document(trip_doc.get('userRef')).get()

        if to_host:
            to_email = host_doc.get('email')
        else:
            to_email = guest_doc.get('email')

        # Data for the request
        data = {
            'personalizations': [
                {
                    'to': [{'email': f'{to_email}'}],
                    'dynamic_template_data': {
                        'office_name': f"{property_doc.get('propertyName')}",
                        'guest_name': f"{guest_doc.get('display_name')}",
                        'property_image': f"{property_doc.get('mainImage')[0]}",
                        'start_date_time': f"{trip_doc.get('tripBeginDateTime')}",
                        'end_date_time': f"{trip_doc.get('tripEndDateTime')}",
                        'base_price': f"${trip_doc.get('tripBaseTotal')}",
                        'addons_price': f"${trip_doc.get('tripAddonTotal')}",
                        'cleaning_fee': f"${property_doc.get('cleaningFee')}",
                        'total_price': f"${trip_doc.get('tripCost')}",
                        'trip_ref': f'{trip_doc.reference}',
                        'image_url': f"{property_doc.get('mainImage')[0]}",
                    },
                }
            ],
            'from': {'email': 'app@bookteamworks.com', 'name': 'Teamworks Executive Suites'},
            'reply_to': {'email': 'support@bookteamworks.com', 'name': 'Teamworks Support'},
            'template_id': f'{template_id}',
        }

        if time:
            data['personalizations'][0]['dynamic_template_data']['time'] = time

        # Send the request
        response = requests.post(url, headers=headers, json=data)

        # Log the response
        app_logger.info('Email sent to %s', to_email)
        app_logger.info('Response: %s', response.text)


def send_complete_email(trip_doc_id: str, property_doc_id: str):
    with logfire.span('send_complete_email'):
        trip_doc = db.collection('trips').document(trip_doc_id).get()
        property_doc = db.collection('properties').document(property_doc_id).get()

        host_complete_email_template_id = 'd-f1698bb27e5c44f982478f61e9f5a2eb'
        guest_complete_email_template_id = 'd-335808be895a413497459fbb3a311a39'

        sendgrid_email(trip_doc, property_doc, host_complete_email_template_id, to_host=True)
        sendgrid_email(trip_doc, property_doc, guest_complete_email_template_id, to_host=False)


def send_reminder_email(trip_doc_id: str, property_doc_id: str, time: int):
    with logfire.span('send_reminder_email'):
        trip_doc = db.collection('trips').document(trip_doc_id).get()
        property_doc = db.collection('properties').document(property_doc_id).get()

        host_reminder_email_template_id = 'd-02adfc13d954429a9e053fba47e9ab60'
        guest_reminder_email_template_id = 'd-5c55d84eb81543819ff8d6aeba12c1e0'

        sendgrid_email(trip_doc, property_doc, host_reminder_email_template_id, time, to_host=True)
        sendgrid_email(trip_doc, property_doc, guest_reminder_email_template_id, time, to_host=False)


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
                        if not trip.exists:
                            app_logger.error('Trip document not found for property %s', prop.id)
                            continue

                        if not trip.exists:
                            app_logger.error('Trip document not found for property %s', prop.id)
                            continue  # Changed from return to continue to process the next trip

                        if (not trip.to_dict().get('complete', False) or trip.to_dict().get('upcoming', False)) and (
                                'tripEndDateTime' in trip.to_dict() and current_time > trip.get('tripEndDateTime')
                        ):
                            try:
                                trip.reference.update({'complete': True, 'upcoming': False})
                                app_logger.info('Trip %s for property %s marked as complete', trip.id, prop.id)

                                complete_trip_sms(trip.id, prop.id)
                                send_complete_email(trip.id, prop.id)

                            except Exception as e:
                                app_logger.error('Failed to update trip %s for property %s: %s', trip.id, prop.id, e)

                        trip_dict = trip.to_dict()
                        if 'tripBeginDateTime' in trip_dict and 'upcoming' in trip_dict and trip_dict['upcoming']:
                            time_difference = trip.get('tripBeginDateTime') - current_time

                            with logfire.span(f'Time till trip starts: {time_difference}'):
                                # Check if current time is exactly one day before the start time of the trip
                                if timedelta(hours=23) < time_difference < timedelta(hours=25):
                                    try:
                                        send_reminder_sms(trip.reference, prop.reference, 24)
                                    except Exception as e:
                                        app_logger.error(
                                            'Failed to send reminder SMS for trip %s for property %s: %s',
                                            trip.id,
                                            prop.id,
                                            e,
                                        )

                                    try:
                                        send_reminder_email(trip.id, prop.id, 24)
                                    except Exception as e:
                                        app_logger.error(
                                            'Failed to send reminder email for trip %s for property %s: %s',
                                            trip.id,
                                            prop.id,
                                            e,
                                        )

                                # Check if current time is exactly one hour before the start time of the trip
                                if timedelta(minutes=59) < time_difference < timedelta(hours=1):
                                    try:
                                        send_reminder_sms(trip.id, prop.id, 1)
                                    except Exception as e:
                                        app_logger.error(
                                            'Failed to send reminder SMS for trip %s for property %s: %s',
                                            trip.id,
                                            prop.id,
                                            e,
                                        )

                                    try:
                                        send_reminder_email(trip.id, prop.id, 1)
                                    except Exception as e:
                                        app_logger.error(
                                            'Failed to send reminder email for trip %s for property %s: %s',
                                            trip.id,
                                            prop.id,
                                            e,
                                        )
                        else:
                            app_logger.info('No trips to action on for property %s', prop.id)

    return True  # Added a return statement for consistency
