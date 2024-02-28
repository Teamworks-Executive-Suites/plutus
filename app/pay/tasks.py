import logging
import os
from datetime import datetime, timedelta

import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.firebase_setup import current_time, db

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# Stripe stuff
def get_document_from_ref(ref):
    """
    Get a document from a given reference.
    :param ref:
    :return:
    """
    collection_id, document_id = ref.split('/')
    document = db.collection(collection_id).document(document_id).get()
    return document


def get_dispute_by_trip_ref(trip_ref):
    """
    Get the dispute associated with a given trip.
    :param trip_ref:
    :return:
    """
    dispute_query = db.collection('disputes').where(filter=FieldFilter('tripRef', '==', trip_ref)).limit(1)
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
        return f'An error occurred: {str(e)}'


def handle_refund(trip_ref, amount):
    """
    Handle a refund for a given trip.
    :param trip_ref:
    :param amount:
    :return:
    """
    logging.info('handle_refund called with trip_ref: %s', trip_ref)

    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return {'status': 404, 'message': 'Trip document not found.'}

    payment_intent_ids = trip.get('stripePaymentIntents')
    if not payment_intent_ids:
        return {'status': 404, 'message': 'No payment intents found on trip.'}

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

            logging.info(refund_result)  # This is for logging purposes, adjust as needed

            refund_details.append(
                {
                    'refunded_amount': refund_amount,
                    'charge_id': charge.id,
                    'payment_intent_id': payment_intent_id,
                }
            )
            total_refunded += refund_amount
            remaining_refund -= refund_amount

    response = {
        'status': 200 if remaining_refund == 0 else 206,
        'message': 'Refund processed successfully.'
        if remaining_refund == 0
        else f'Partial refund processed. Unable to refund {remaining_refund} out of requested {amount}.',
        'total_refunded': total_refunded,
        'refund_details': refund_details,
    }

    return response


def process_extra_charge(trip_ref, dispute_ref):
    """
    Process an extra charge for a given trip in the case of a dispute.

    Parameters:
    - trip_ref: The reference to the trip for which the extra charge is to be processed.

    Returns:
    - A dictionary containing the result of the extra charge process or an error message.
    """

    # Initiate a response dictionary
    response = {'status': None, 'message': None, 'details': {}}

    # Retrieve the trip document
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        response['status'] = 404
        response['message'] = 'Trip document not found.'
        return response

    # Retrieve the dispute associated with the trip
    # dispute = get_dispute_by_trip_ref(trip_ref)

    dispute = get_document_from_ref(dispute_ref)

    if not dispute:
        response['status'] = 404
        response['message'] = 'No dispute found for this trip.'
        return response

    # Avoid code duplication by retrieving PaymentIntent once
    first_payment_intent = stripe.PaymentIntent.retrieve(trip.get('stripePaymentIntents')[0])
    stripe_customer = first_payment_intent.customer
    payment_method = first_payment_intent.payment_method

    try:
        # Create a new PaymentIntent for the extra charge
        extra_charge_pi = stripe.PaymentIntent.create(
            amount=int(dispute.get('disputeAmount') * 100),  # Ensure the amount is an integer
            currency='usd',
            automatic_payment_methods={'enabled': True},
            customer=stripe_customer,
            payment_method=payment_method,
            off_session=True,
            confirm=True,
        )

        # Update dispute with the new PaymentIntent ID
        dispute.reference.update({'paymentIntent': extra_charge_pi.id})

        # Update the trip with the new PaymentIntent ID
        current_payment_intents = trip.get('stripePaymentIntents')
        current_payment_intents.append(extra_charge_pi.id)
        trip.reference.update({'stripePaymentIntents': current_payment_intents})

        # Update response for successful extra charge
        response['status'] = 200
        response['message'] = 'Extra charge processed successfully.'
        response['details']['payment_intent'] = extra_charge_pi

        logging.info('Extra charge processed successfully: %s', extra_charge_pi)

        return response
    except stripe.error.CardError as e:
        err = e.error
        response['status'] = 400
        response['message'] = 'Failed to process extra charge due to a card error.'
        response['details']['error_code'] = err.code
        response['details']['error_message'] = str(e)

        logging.error('Failed to process extra charge due to a card error: %s', err.code)

        return response
    except Exception as e:
        response['status'] = 500
        response['message'] = 'An unexpected error occurred while processing the extra charge.'
        response['details']['error_message'] = str(e)

        logging.error('An unexpected error occurred while processing the extra charge: %s', str(e))

        return response


def process_cancel_refund(trip_ref):
    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        return {'status': 404, 'message': 'Trip document not found.'}

    property_ref = trip.get('propertyRef')
    property = get_document_from_ref(f'properties/{property_ref}')

    if not property.exists:
        return {'status': 404, 'message': 'Property document not found.'}

    cancellation_policy = property.get('cancellationPolicy')
    logging.info('Cancellation policy: %s', cancellation_policy)

    trip_begin_time = trip.get('tripBeginDateTime')
    trip_begin_time = datetime.fromtimestamp(trip_begin_time, tz=current_time.tzinfo)
    time_difference = current_time - trip_begin_time  # from start to now

    payment_intent_ids = trip.get('stripePaymentIntents')
    if not payment_intent_ids:
        return {'status': 404, 'message': 'No payment intents found on trip.'}

    total_refunded = 0
    refund_details = []
    for payment_intent_id in payment_intent_ids:
        charges = stripe.Charge.list(payment_intent=payment_intent_id)
        for charge in charges.auto_paging_iter():
            if charge.status != 'succeeded':
                continue

            already_refunded = charge.amount_refunded
            refundable_amount = charge.amount - already_refunded

            if cancellation_policy == 'Very Flexible':
                if time_difference <= timedelta(hours=24):
                    refund_amount = refundable_amount
                    refund_reason = '24 or more before booking - 100% refund'
                else:
                    refund_amount = 0
                    refund_reason = 'Less than 24 hours before booking - no refund'
            elif cancellation_policy == 'Flexible':
                if time_difference >= timedelta(days=7):
                    refund_amount = refundable_amount
                    refund_reason = '7 or more days before booking - 100% refund'
                elif timedelta(hours=24) <= time_difference < timedelta(days=7):
                    refund_amount = refundable_amount // 2
                    refund_reason = 'Between 24 hours and 7 days before booking - 50% refund'
                else:
                    refund_amount = 0
                    refund_reason = 'Less than 24 hours before booking - no refund'
            elif cancellation_policy == 'Standard 30 Day':
                if time_difference >= timedelta(days=30):
                    refund_amount = refundable_amount
                    refund_reason = '30 or more days before booking - 100% refund'
                elif timedelta(days=7) <= time_difference < timedelta(days=30):
                    refund_amount = refundable_amount // 2
                    refund_reason = 'Between 7 and 30 days before booking - 50% refund'
                else:
                    refund_amount = 0
                    refund_reason = 'Less than 7 days before booking - no refund'
            elif cancellation_policy == 'Standard 90 Day':
                if time_difference >= timedelta(days=90):
                    refund_amount = refundable_amount
                    refund_reason = '90 or more days before booking - 100% refund'
                elif timedelta(days=30) <= time_difference < timedelta(days=90):
                    refund_amount = refundable_amount // 2
                    refund_reason = 'Between 30 and 90 days before booking - 50% refund'
                else:
                    refund_amount = 0
                    refund_reason = 'Less than 30 days before booking - no refund'
            else:
                refund_amount = 0
                refund_reason = (
                    f'Cancellation policy not recognized: {cancellation_policy} - no refund - please contact support'
                )

            if refund_amount > 0:
                process_refund(charge.id, refund_amount)
                refund_details.append(
                    {
                        'refunded_amount': refund_amount,
                        'reason': refund_reason,
                        'charge_id': charge.id,
                        'payment_intent_id': payment_intent_id,
                    }
                )
                total_refunded += refund_amount
            else:
                refund_details.append(
                    {
                        'refunded_amount': 0,
                        'reason': refund_reason,
                        'charge_id': charge.id,
                        'payment_intent_id': payment_intent_id,
                    }
                )

    response = {
        'status': 200,
        'message': 'Refund processed.',
        'total_refunded': total_refunded,
        'refund_details': refund_details,
        'cancellation_policy': cancellation_policy,
    }

    return response
