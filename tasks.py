import json
import os
from datetime import datetime, timezone, timedelta

import firebase_admin
import requests
import stripe
from devtools import debug
from dotenv import load_dotenv
from firebase_admin import firestore, credentials
from google.cloud.firestore_v1 import FieldFilter
from icalendar import Calendar as iCalCalendar
from ics import Calendar, Event

load_dotenv()
tz = timezone.utc

current_time = datetime.now(timezone.utc)

cred = credentials.Certificate(json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')))

app = firebase_admin.initialize_app(cred)
db = firestore.client()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# Stripe stuff
def get_document_from_ref(trip_ref):
    """
    Get a document from a given reference.
    :param trip_ref:
    :return:
    """
    collection_id, document_id = trip_ref.split('/')
    trip = db.collection(collection_id).document(document_id).get()
    return trip


def get_dispute_by_trip_ref(trip_ref):
    """
    Get the dispute associated with a given trip.
    :param trip_ref:
    :return:
    """
    dispute_query = db.collection('disputes').where(filter=FieldFilter("tripRef", "==", trip_ref)).limit(1)
    dispute_documents = list(dispute_query.stream())
    return dispute_documents[0] if dispute_documents else None


def process_refund(charge_id, amount):
    """
    Process a refund for a given charge.
    :param charge_id:
    :param amount:
    :return:
    """
    try:
        refund = stripe.Refund.create(
            charge=charge_id,
            amount=amount,
        )
        return refund.status == 'succeeded'
    except Exception as e:
        return f"An error occurred: {str(e)}"


def handle_refund(trip_ref, amount):
    """
    Handle a refund for a given trip.
    :param trip_ref:
    :param amount:
    :return:
    """
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return {"status": 404, "message": "Trip document not found."}

    payment_intent_ids = trip.get("stripePaymentIntents")
    if not payment_intent_ids:
        return {"status": 404, "message": "No payment intents found on trip."}

    total_refunded = 0
    refund_details = []
    remaining_refund = amount
    for payment_intent_id in payment_intent_ids:
        if remaining_refund <= 0:
            break

        charges = stripe.Charge.list(payment_intent=payment_intent_id)
        for charge in charges.auto_paging_iter():
            if charge.status != 'succeeded' or remaining_refund <= 0:
                continue

            already_refunded = charge.amount_refunded
            refundable_amount = charge.amount - already_refunded

            if refundable_amount <= 0:
                continue

            refund_amount = min(remaining_refund, refundable_amount)
            refund_result = process_refund(charge.id, refund_amount)

            debug(refund_result)  # This is for debugging purposes, adjust as needed

            refund_details.append({
                "refunded_amount": refund_amount,
                "charge_id": charge.id,
                "payment_intent_id": payment_intent_id
            })
            total_refunded += refund_amount
            remaining_refund -= refund_amount

    response = {
        "status": 200 if remaining_refund == 0 else 206,
        "message": "Refund processed successfully." if remaining_refund == 0 else f"Partial refund processed. Unable to refund {remaining_refund} out of requested {amount}.",
        "total_refunded": total_refunded,
        "refund_details": refund_details
    }

    return response


def process_extra_charge(trip_ref):
    """
    Process an extra charge for a given trip in the case of a dispute.

    Parameters:
    - trip_ref: The reference to the trip for which the extra charge is to be processed.

    Returns:
    - A dictionary containing the result of the extra charge process or an error message.
    """

    # Initiate a response dictionary
    response = {"status": None, "message": None, "details": {}}

    # Retrieve the trip document
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        response["status"] = 404
        response["message"] = "Trip document not found."
        return response

    # Retrieve the dispute associated with the trip
    dispute = get_dispute_by_trip_ref(trip_ref)

    if not dispute:
        response["status"] = 404
        response["message"] = "No dispute found for this trip."
        return response

    # Avoid code duplication by retrieving PaymentIntent once
    first_payment_intent = stripe.PaymentIntent.retrieve(trip.get("stripePaymentIntents")[0])
    stripe_customer = first_payment_intent.customer
    payment_method = first_payment_intent.payment_method

    try:
        # Create a new PaymentIntent for the extra charge
        extra_charge_pi = stripe.PaymentIntent.create(
            amount=int(dispute.get("disputeAmount") * 100),  # Ensure the amount is an integer
            currency='usd',
            automatic_payment_methods={"enabled": True},
            customer=stripe_customer,
            payment_method=payment_method,
            off_session=True,
            confirm=True,
        )

        # Update dispute with the new PaymentIntent ID
        dispute.reference.update({"paymentIntent": extra_charge_pi.id})

        # Update the trip with the new PaymentIntent ID
        current_payment_intents = trip.get("stripePaymentIntents")
        current_payment_intents.append(extra_charge_pi.id)
        trip.reference.update({"stripePaymentIntents": current_payment_intents})

        # Update response for successful extra charge
        response["status"] = 200
        response["message"] = "Extra charge processed successfully."
        response["details"]["payment_intent"] = extra_charge_pi

        return response
    except stripe.error.CardError as e:
        err = e.error
        response["status"] = 400
        response["message"] = "Failed to process extra charge due to a card error."
        response["details"]["error_code"] = err.code
        response["details"]["error_message"] = str(e)

        return response
    except Exception as e:
        response["status"] = 500
        response["message"] = "An unexpected error occurred while processing the extra charge."
        response["details"]["error_message"] = str(e)

        return response



def process_cancel_refund(trip_ref):
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return {"status": 404, "message": "Trip document not found."}

    trip_begin_time = trip.get("tripBeginDateTime")

    time_difference = trip_begin_time - current_time

    payment_intent_ids = trip.get("stripePaymentIntents")
    if not payment_intent_ids:
        return {"status": 404, "message": "No payment intents found on trip."}

    total_refunded = 0
    refund_details = []
    for payment_intent_id in payment_intent_ids:
        charges = stripe.Charge.list(payment_intent=payment_intent_id)
        for charge in charges.auto_paging_iter():
            if charge.status != 'succeeded':
                continue

            already_refunded = charge.amount_refunded
            refundable_amount = charge.amount - already_refunded

            if time_difference >= timedelta(days=7):
                refund_amount = refundable_amount
                refund_reason = "7 or more days before trip"
            elif timedelta(hours=48) <= time_difference < timedelta(days=7):
                refund_amount = refundable_amount // 2
                refund_reason = "Between 48 hours and 7 days before trip"
            else:
                refund_amount = 0
                refund_reason = "Less than 48 hours before trip"

            if refund_amount > 0:
                process_refund(charge.id, refund_amount)
                refund_details.append({
                    "refunded_amount": refund_amount,
                    "reason": refund_reason,
                    "charge_id": charge.id,
                    "payment_intent_id": payment_intent_id
                })
                total_refunded += refund_amount
            else:
                refund_details.append({
                    "refunded_amount": 0,
                    "reason": refund_reason,
                    "charge_id": charge.id,
                    "payment_intent_id": payment_intent_id
                })

    response = {
        "status": 200,
        "message": "Refund processed.",
        "total_refunded": total_refunded,
        "refund_details": refund_details
    }

    return response


# Calendar stuff

def create_cal_for_property(propertyRef):
    debug("create_cal_for_property")

    collection_id, document_id = propertyRef.split('/')
    trips_ref = db.collection("trips")
    property_ref = db.collection('properties').document(document_id).get()
    property_trips = (trips_ref
                      .where(filter=FieldFilter("propertyRef", "==", property_ref.reference))
                      .where(filter=FieldFilter("isExternal", "==", False))
                      .stream()
                      )

    ics_file_path = f'calendars/{property_ref.get("propertyName")}.ics'

    # If calendar file exists, load it, else create a new calendar
    if os.path.exists(ics_file_path):
        with open(ics_file_path, 'r') as ics_file:
            cal = Calendar(ics_file.read())
    else:
        cal = Calendar()


    for trip in property_trips:
        trip_begin_datetime = trip.get("tripBeginDateTime")

        # Check if the trip is in the future
        if trip_begin_datetime > current_time:
            user_ref = trip.get("userRef").id
            user = db.collection("users").document(user_ref).get()
            debug(f'{user.get("email")} | {property_ref.get("propertyName")}')

            cal_event = Event()
            cal_event.name = f'{user.get("email")} | {property_ref.get("propertyName")}'
            cal_event.begin = trip_begin_datetime
            cal_event.end = trip.get("tripEndDateTime")

            # Adding event to the calendar
            cal.events.add(cal_event)

    # Writing the updated calendar back to the file
    with open(ics_file_path, 'w') as ics_file:
        ics_file.writelines(cal)

    return ics_file_path


def create_trips_from_ics(property_ref, ics_link):
    debug("create_trips_from_ics")

    collection_id, document_id = property_ref.split('/')

    property_ref = db.collection(collection_id).document(document_id).get()

    response = requests.get(ics_link)
    if response.status_code != 200:
        return "Failed to fetch the iCalendar file."

    ics_data = response.text

    cal = iCalCalendar.from_ical(ics_data)
    trips_ref = db.collection("trips")

    for event in cal.walk('VEVENT'):
        debug(event)

        # convert ical datetime to firestore datetime
        eventstart = event.get('DTSTART').dt

        # Check if the event is in the future
        if eventstart > current_time:
            eventend = event.get('DTEND').dt

            trip_begin_datetime = datetime(eventstart.year, eventstart.month, eventstart.day, tzinfo=tz)
            trip_end_datetime = datetime(eventend.year, eventend.month, eventend.day, tzinfo=tz)

            trip_data = {
                "isExternal": True,
                "propertyRef": property_ref.reference,
                "tripBeginDateTime": trip_begin_datetime,
                "tripEndDateTime": trip_end_datetime,
            }
            trips_ref.add(trip_data)

    return True




def update_calendars():
    debug("Updating Calendars")

    properties_ref = db.collection("properties")
    properties = properties_ref.stream()

    for prop in properties:

        # Sync External Calendars
        try:
            external_calendar_data = prop.get("externalCalendar")
            if external_calendar_data and external_calendar_data.exists:
                create_trips_from_ics(prop.reference, external_calendar_data)
        except KeyError:
            pass  # Handle the case where the "externalCalendar" key doesn't exist

        # Sync Internal Calendars
        create_cal_for_property(prop.reference.path)

    return True


# Server Functions

def auto_complete():
    '''
    function called every hour,
    checks if trip is complete and if current time is past trip end time

    :param trip_ref: The trip reference to check.
    '''

    debug('Running Auto Complete')
    # for every property
    properties_ref = db.collection("properties").stream()
    for prop in properties_ref:
        #  for every trip in property
        trips = db.collection("trips").where(filter=FieldFilter("propertyRef", "==", prop.reference)).stream()
        for trip in trips:

            if not trip.exists:
                return "Trip document not found."

            if not trip.get("complete") and (current_time > trip.get("tripEndDateTime")):
                trip.reference.update({"complete": True})
                debug(f'Trip {trip.reference.path} marked as complete')
