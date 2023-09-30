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


def refund_logic(payment_intent_id, amount):
    """
    Refund a given amount for a given payment intent.
    :param payment_intent_id:
    :param amount:
    :return:
    """
    try:
        charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
        if charge.data:
            refund_amount = int(amount * 100)
            return process_refund(charge.data[0].id, refund_amount)
        else:
            return "Charge not found."
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
        return "Trip document not found."

    debug(trip)
    payment_intent_id = trip.get("stripePaymentIntents")[0]
    refund = refund_logic(payment_intent_id, amount)
    return refund


def process_extra_charge(trip_ref):  # test with the payment intents having no edit (setup_future_usage)
    """
    Process an extra charge for a given trip in the case of a dispute.

    Parameters:
    - trip_ref: The reference to the trip for which the extra charge is to be processed.

    Returns:
    - A dictionary containing the result of the extra charge process or an error message.
    """

    # Retrieve the trip document
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return {"error": "Trip document not found."}

    # Retrieve the dispute associated with the trip
    dispute = get_dispute_by_trip_ref(trip_ref)

    if not dispute:
        return {"error": "No dispute found for this trip."}

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
        return {"success": extra_charge_pi}
    except stripe.error.CardError as e:
        err = e.error
        # Consider logging the error instead of printing
        print("Code is: %s" % err.code)
        return {"error": f"Failed to process extra charge due to a card error: {err.code}"}
    except Exception as e:
        # Catch any other exceptions
        print(f"An unexpected error occurred: {e}")
        return {"error": "An unexpected error occurred while processing the extra charge."}


def process_cancel_refund(trip_ref):
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return "Trip document not found."

    current_time = datetime.now(tz)
    trip_begin_time = trip.get("tripBeginDateTime")

    time_difference = trip_begin_time - current_time
    refund_amount = 0

    payment_intent_ids = trip.get("setupPaymentIntents")  # Changed to get all payment intent IDs
    if not payment_intent_ids:
        return "no payment intents found on trip"

    refund_results = []
    for payment_intent_id in payment_intent_ids:
        charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
        if charge.data:
            original_amount = charge.data[0].amount

            if time_difference >= timedelta(days=7):
                refund_amount = original_amount  # full refund
            elif timedelta(hours=48) <= time_difference < timedelta(days=7):
                refund_amount = original_amount // 2  # half refund
            # If time_difference is less than 48 hours, refund_amount remains 0

            if refund_amount:
                refund_result = process_refund(charge.data[0].id, refund_amount)
                refund_results.append(refund_result)
            else:
                refund_results.append("Refund not applicable due to close proximity to trip start time.")
        else:
            refund_results.append("No charge found for this payment intent.")

    return refund_results


# Calendar stuff

def create_cal_for_property(propertyRef):
    debug("create_cal_for_property")

    debug(propertyRef)

    collection_id, document_id = propertyRef.split('/')
    trips_ref = db.collection("trips")
    property_ref = db.collection('properties').document(document_id).get()
    property_trips = (trips_ref
                      .where(filter=FieldFilter("propertyRef", "==", property_ref.reference))
                      .where(filter=FieldFilter("isExternal", "==", False))
                      .stream()
                      )

    # check if trip has been completed
    current_time = datetime.now(tz)

    cal = Calendar()
    for trip in property_trips:
        user_ref = trip.get("userRef").id
        user = db.collection("users").document(user_ref).get()
        debug(f'{user.get("email")} | {property_ref.get("propertyName")}')

        cal_event = Event()
        cal_event.name = f'{user.get("email")} | {property_ref.get("propertyName")}'
        cal_event.begin = trip.get("tripBeginDateTime")
        cal_event.end = trip.get("tripEndDateTime")

        if current_time > trip.get("tripEndDateTime"):
            trip.reference.update({"isComplete": True})

        cal.events.add(cal_event)

    # Create an .ics file
    ics_file_path = f'calendars/{property_ref.get("propertyName")}.ics'
    with open(ics_file_path, "w") as ics_file:
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


debug("Starting Calendar Sync")


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
    checks if trip is complete and not refunded and if it is 72 hours after the trip end date
    it marks the trip as complete

    :param trip_ref: The trip reference to check.
    '''

    # for every property
    properties_ref = db.collection("properties")
    for property in properties_ref:
        #  for every trip in property
        trips_ref = db.collection("trips").where(filter=FieldFilter("propertyRef", "==", property.reference))

        for trip in trips_ref:
            if not trip.exists:
                return "Trip document not found."

            current_time = datetime.now(tz)
            auto_complete_time = current_time + timedelta(hours=72)

            if not trip.get("isComplete") and (auto_complete_time > trip.get("tripEndDateTime")):
                trip.reference.update({"isComplete": True})
