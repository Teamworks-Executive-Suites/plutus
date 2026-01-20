import hashlib
import os
from datetime import timedelta

import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.firebase_setup import current_time, db
from app.models import ActorRole, Status, Transaction, TransactionType
from app.pay._utils import app_logger
from app.utils import settings

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


def generate_refund_idempotency_key(trip_ref, charge_id, amount, refund_type='manual'):
    """
    Generate a unique idempotency key for a refund operation.
    
    :param trip_ref: Trip reference
    :param charge_id: Stripe charge ID
    :param amount: Refund amount in cents
    :param refund_type: Type of refund ('manual' or 'cancel')
    :return: Idempotency key (40 characters)
    """
    key_data = f"{trip_ref}:{charge_id}:{amount}:{refund_type}"
    # Hash and truncate to 40 chars for brevity while maintaining uniqueness
    # SHA256 provides sufficient uniqueness even when truncated
    return hashlib.sha256(key_data.encode()).hexdigest()[:40]


def calculate_fee(amount_cents, fee_rate):
    """
    Calculate the fee for a given amount.
    :param amount_cents:
    :param fee_rate:
    :return:
    """
    app_logger.info('Calculating fee for amount: %s', amount_cents)
    fee = int(amount_cents * fee_rate)
    app_logger.info('Fee calculated: %s', fee)
    return fee


def calculate_fees(amount_cents):
    """
    Calculate the fees for a given amount.
    :param amount_cents:
    :return host_fee, guest_fee:
    """
    app_logger.info('Calculating fees for amount: %s', amount_cents)
    host_fee = calculate_fee(amount_cents, settings.host_fee)
    guest_fee = calculate_fee(amount_cents, settings.guest_fee)
    net_fee = amount_cents - host_fee - guest_fee
    app_logger.info('Fees calculated: %s', {'host_fee': host_fee, 'guest_fee': guest_fee, 'net_fee': net_fee})
    return host_fee, guest_fee, net_fee


# Stripe stuff
def get_document_from_ref(ref):
    """
    Get a document from a given reference.
    :param ref:
    :return:
    """
    collection_id, document_id = ref.split('/')
    app_logger.info('Getting document from collection %s with ID %s', collection_id, document_id)
    try:
        document = db.collection(collection_id).document(document_id).get()
        return document
    except Exception as e:
        app_logger.error('An error occurred in get_document_from_ref for %s: %s', ref, str(e))


def get_dispute_by_trip_ref(trip_ref):
    """
    Get the dispute associated with a given trip.
    :param trip_ref:
    :return:
    """
    dispute_query = db.collection('disputes').where(filter=FieldFilter('tripRef', '==', trip_ref)).limit(1)
    dispute_documents = list(dispute_query.stream())
    return dispute_documents[0] if dispute_documents else None


def process_refund(charge_id, amount, idempotency_key=None):
    """
    Process a refund for a given charge.
    :param charge_id:
    :param amount:
    :param idempotency_key: Optional idempotency key to prevent duplicate refunds
    :return:
    """
    try:
        refund_params = {
            'charge': charge_id,
            'amount': amount,
        }
        if idempotency_key:
            refund_params['idempotency_key'] = idempotency_key
        
        refund = stripe.Refund.create(**refund_params)
        app_logger.info('Refund processed: %s', refund)
        return refund.status == 'succeeded'
    except Exception as e:
        app_logger.error('An error occurred in process_refund: %s', str(e))
        return f'An error occurred: {str(e)}'


def handle_refund(trip_ref, amount, actor_ref):
    """
    Handle a refund for a given trip.
    :param trip_ref:
    :param amount:
    :param actor_ref:
    :return:
    """
    app_logger.info('handle_refund called with trip_ref: %s', trip_ref)

    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        app_logger.error('Trip document not found.')
        return {'status': 404, 'message': 'Trip document not found.'}

    # Check for existing refund transactions to prevent duplicates
    existing_refunds = (
        db.collection('transactions')
        .where(filter=FieldFilter('tripRef', '==', trip_ref))
        .where(filter=FieldFilter('type', '==', TransactionType.refund))
        .where(filter=FieldFilter('refundedAmountCents', '==', amount))
        .limit(1)
        .stream()
    )
    
    existing_refund_list = list(existing_refunds)
    if existing_refund_list:
        app_logger.warning('Duplicate refund request detected for trip %s with amount %s', trip_ref, amount)
        return {
            'status': 409,
            'message': 'A refund transaction with this amount already exists for this trip.',
        }

    payment_intent_ids = trip.get('stripePaymentIntents')
    if not payment_intent_ids:
        app_logger.error('No payment intents found on trip.')
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
            
            # Generate idempotency key to prevent duplicate refunds
            idempotency_key = generate_refund_idempotency_key(trip_ref, charge.id, refund_amount, 'manual')
            
            process_refund(charge.id, refund_amount, idempotency_key)

            refund_details.append(
                {
                    'refunded_amount': refund_amount,
                    'charge_id': charge.id,
                    'payment_intent_id': payment_intent_id,
                }
            )
            total_refunded += refund_amount
            remaining_refund -= refund_amount

    # transaction from platform to client

    client_transaction = Transaction(
        actorRef=f'users/{actor_ref}',
        actorRole=ActorRole.platform,
        receiverRef=f'users/{trip.get("userRef")}',
        receiverRole=ActorRole.client,
        transferId=None,
        status=Status.completed,
        type=TransactionType.refund,
        createdAt=current_time,
        processedAt=current_time,
        notes='Refund processed on plutus',
        guestFeeCents=0,
        hostFeeCents=0,
        netFeeCents=0,
        grossFeeCents=0,
        tripRef=trip_ref,
        refundedAmountCents=total_refunded,
        paymentIntentIds=payment_intent_ids,
        mergedTransactions=[],
    ).dict()

    db.collection('transactions').add(client_transaction)

    # transaction from host to platform

    host_transaction = Transaction(
        actorRef=f'users/{actor_ref}',
        actorRole=ActorRole.host,
        receiverRef='platform',
        receiverRole=ActorRole.platform,
        transferId=None,
        status=Status.in_escrow,
        type=TransactionType.refund,
        createdAt=current_time,
        processedAt=current_time,
        notes='Refund processed on plutus',
        guestFeeCents=0,
        hostFeeCents=0,
        netFeeCents=0,
        grossFeeCents=0,
        tripRef=trip_ref,
        refundedAmountCents=total_refunded,
        paymentIntentIds=payment_intent_ids,
        mergedTransactions=[],
    ).dict()

    db.collection('transactions').add(host_transaction)

    response = {
        'status': 200 if remaining_refund == 0 else 206,
        'message': 'Refund processed successfully.'
        if remaining_refund == 0
        else f'Partial refund processed. Unable to refund {remaining_refund} out of requested {amount}.',
        'total_refunded': total_refunded,
        'refund_details': refund_details,
    }
    return response


def process_extra_charge(trip_ref, dispute_ref, actor_ref):
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
        # Update dispute status to denied if trip not found
        dispute = get_document_from_ref(dispute_ref)
        if dispute and dispute.exists:
            dispute.reference.update({'status': 'denied'})
        response['status'] = 404
        response['message'] = 'Trip document not found.'
        app_logger.error('Trip document not found')
        return response

    # Retrieve the dispute associated with the trip
    dispute = get_document_from_ref(dispute_ref)

    if not dispute or not dispute.exists:
        response['status'] = 404
        response['message'] = 'No dispute found for this trip.'
        app_logger.error('No dispute found for this trip')
        return response

    # Set dispute status to pending before processing
    dispute.reference.update({'status': 'pending'})

    # Avoid code duplication by retrieving PaymentIntent once
    first_payment_intent = stripe.PaymentIntent.retrieve(trip.get('stripePaymentIntents')[0])
    stripe_customer = first_payment_intent.customer
    payment_method = first_payment_intent.payment_method

    try:
        # Create a new PaymentIntent for the extra charge
        extra_charge_pi = stripe.PaymentIntent.create(
            amount=round(dispute.get('disputeAmount')),  # Round to nearest cent (disputeAmount is in cents)
            currency='usd',
            automatic_payment_methods={'enabled': True},
            customer=stripe_customer,
            payment_method=payment_method,
            off_session=True,
            confirm=True,
        )

        # Update dispute with the new PaymentIntent ID and set status to completed
        dispute.reference.update({'paymentIntent': extra_charge_pi.id, 'status': 'completed'})

        # Update the trip with the new PaymentIntent ID
        current_payment_intents = trip.get('stripePaymentIntents')
        current_payment_intents.append(extra_charge_pi.id)
        trip.reference.update({'stripePaymentIntents': current_payment_intents})

        # Update response for successful extra charge
        response['status'] = 200
        response['message'] = 'Extra charge processed successfully.'
        response['details']['payment_intent'] = extra_charge_pi

        app_logger.info('Extra charge processed successfully: %s', extra_charge_pi)

        # Round dispute amount to nearest cent (disputeAmount is in cents but may have fractional part)
        dispute_amount_cents = round(dispute.get('disputeAmount'))
        host_fee, guest_fee, net_fee = calculate_fees(dispute_amount_cents)

        try:
            # create the transactions for the extra charge
            # transaction from client to platform
            client_transaction = Transaction(
                actorRef=f'users/{actor_ref}',
                actorRole=ActorRole.client,
                receiverRef=f'users/{settings.platform_user_id}',
                receiverRole=ActorRole.platform,
                transferId=None,
                status=Status.completed,
                type=TransactionType.payment,
                createdAt=current_time,
                processedAt=current_time,
                notes='Extra charge processed on plutus',
                guestFeeCents=0,
                hostFeeCents=0,
                netFeeCents=0,
                grossFeeCents=dispute_amount_cents,
                tripRef=trip_ref,
                refundedAmountCents=0,
                paymentIntentIds=[extra_charge_pi.id],
                mergedTransactions=[],
            ).model_dump()

            db.collection('transactions').add(client_transaction)

            # transaction from platform to host
            host_transaction = Transaction(
                actorRef=f'users/{settings.platform_user_id}',
                actorRole=ActorRole.platform,
                receiverRef=trip.get('propertyRef').id
                if hasattr(trip.get('propertyRef'), 'id')
                else str(trip.get('propertyRef')),
                receiverRole=ActorRole.host,
                transferId=None,
                status=Status.in_escrow,
                type=TransactionType.payment,
                createdAt=current_time,
                processedAt=current_time,
                notes='Extra charge processed on plutus',
                guestFeeCents=guest_fee,
                hostFeeCents=host_fee,
                netFeeCents=net_fee,
                grossFeeCents=dispute_amount_cents,
                tripRef=trip_ref,
                refundedAmountCents=0,
                paymentIntentIds=[extra_charge_pi.id],
                mergedTransactions=[],
            ).model_dump()

            db.collection('transactions').add(host_transaction)
        except Exception as e:
            # Update dispute status to failed if transaction creation fails
            dispute.reference.update({'status': 'failed'})
            response['status'] = 500
            response['message'] = 'An unexpected error occurred while processing the extra charge.'
            response['details']['error_message'] = str(e)
            app_logger.error('An unexpected error occurred while processing the extra charge: %s', str(e))
            return response

        return response

    except stripe.error.CardError as e:
        # Update dispute status to failed on card error
        dispute.reference.update({'status': 'failed'})
        err = e.error
        response['status'] = 400
        response['message'] = 'Failed to process extra charge due to a card error.'
        response['details']['error_code'] = err.code
        response['details']['error_message'] = str(e)
        app_logger.error('Failed to process extra charge due to a card error: %s', err.code)
        return response
    except Exception as e:
        # Update dispute status to failed on general error
        dispute.reference.update({'status': 'failed'})
        response['status'] = 500
        response['message'] = 'An unexpected error occurred while processing the extra charge.'
        response['details']['error_message'] = str(e)

        app_logger.error('An unexpected error occurred while processing the extra charge: %s', str(e))
        return response


def process_cancel_refund(trip_ref, full_refund=False, actor_ref=None):
    """
    Process a refund for a given trip based on the cancellation policy of the property.

    params:
    - trip_ref: The reference to the trip for which the refund is to be processed.
    - full_refund: A boolean indicating whether a full refund is requested.
    """

    trip = get_document_from_ref(trip_ref)

    if not trip.exists:
        app_logger.error('Trip document not found.')
        return {'status': 404, 'message': 'Trip document not found.'}
    
    # Check for existing cancel_refund transactions to prevent duplicates
    existing_cancel_refunds = (
        db.collection('transactions')
        .where(filter=FieldFilter('tripRef', '==', trip_ref))
        .where(filter=FieldFilter('type', '==', TransactionType.refund))
        .where(filter=FieldFilter('actorRole', '==', ActorRole.host))
        .limit(1)
        .stream()
    )
    
    existing_cancel_refund_list = list(existing_cancel_refunds)
    if existing_cancel_refund_list:
        app_logger.warning('Duplicate cancel_refund request detected for trip %s', trip_ref)
        return {
            'status': 409,
            'message': 'A cancellation refund transaction already exists for this trip.',
        }

    property_ref = trip.get('propertyRef')
    property = get_document_from_ref(f'properties/{property_ref.id}')

    if not property.exists:
        app_logger.error('Property document not found.')
        return {'status': 404, 'message': 'Property document not found.'}

    cancellation_policy = property.get('cancellationPolicy')
    app_logger.info('Cancellation policy: %s', cancellation_policy)

    trip_begin_time = trip.get('tripBeginDateTime')
    trip_begin_time = trip_begin_time.astimezone(current_time.tzinfo)
    time_difference = current_time - trip_begin_time  # from start to now

    payment_intent_ids = trip.get('stripePaymentIntents')
    if not payment_intent_ids:
        app_logger.error('No payment intents found on trip.')
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

            if full_refund:
                refund_amount = refundable_amount
                refund_reason = 'Host cancelled Booking - Full Refund'

            else:
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
                    refund_reason = f'Cancellation policy not recognized: {cancellation_policy} - no refund - please contact support'

            if refund_amount > 0:
                # Generate idempotency key to prevent duplicate refunds
                idempotency_key = generate_refund_idempotency_key(trip_ref, charge.id, refund_amount, 'cancel')
                
                process_refund(charge.id, refund_amount, idempotency_key)
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

    # create a refund transaction document
    transaction = Transaction(
        actorRef=f'users/{actor_ref}',
        actorRole=ActorRole.host,
        receiverRef=trip.get('userRef').id if hasattr(trip.get('userRef'), 'id') else str(trip.get('userRef')),
        receiverRole=ActorRole.client,
        transferId=None,
        status=Status.completed,
        type=TransactionType.refund,
        createdAt=current_time,
        processedAt=current_time,
        notes='Refund processed on plutus',
        guestFeeCents=0,
        hostFeeCents=0,
        netFeeCents=0,
        grossFeeCents=0,
        tripRef=trip_ref,
        refundedAmountCents=total_refunded,
        paymentIntentIds=payment_intent_ids,
        mergedTransactions=[],
    ).dict()

    db.collection('transactions').add(transaction)

    response = {
        'status': 200,
        'message': 'Refund processed.',
        'total_refunded': total_refunded,
        'refund_details': refund_details,
        'cancellation_policy': cancellation_policy,
    }
    return response


def process_off_session_payment(customer_id, amount, currency, trip_ref, guest_email):
    """
    Process an off-session payment for booking directly on behalf of a guest.
    Uses the guest's saved payment method to charge them without interaction.

    :param customer_id: Guest email (will lookup Stripe customer)
    :param amount: Amount in cents
    :param currency: Currency code (default: 'usd')
    :param trip_ref: Reference to the trip document
    :param guest_email: Guest email for error messages
    :return: Response dict with payment status
    """
    app_logger.info('process_off_session_payment called for trip %s, amount %s', trip_ref, amount)

    try:
        # Lookup Stripe customer by email
        customers = stripe.Customer.list(email=guest_email, limit=1)

        if not customers.data:
            app_logger.error('No Stripe customer found for email: %s', guest_email)
            return {
                'status': 'failed',
                'error': 'No payment method on file',
            }

        stripe_customer = customers.data[0]
        app_logger.info('Found Stripe customer: %s', stripe_customer.id)

        # Get customer's default payment method
        default_pm = stripe_customer.invoice_settings.default_payment_method

        if not default_pm:
            app_logger.error('No default payment method for customer: %s', stripe_customer.id)
            return {
                'status': 'failed',
                'error': 'No payment method on file',
            }

        # Create and confirm payment intent off-session
        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            customer=stripe_customer.id,
            payment_method=default_pm,
            off_session=True,
            confirm=True,
            metadata={
                'trip_ref': trip_ref,
                'guest_email': guest_email,
                'booked_by_platform': 'true',
            },
        )

        app_logger.info('Off-session payment created successfully: %s', payment_intent.id)

        return {
            'paymentIntentId': payment_intent.id,
            'status': payment_intent.status,
        }

    except stripe.error.CardError as e:
        app_logger.error('Card error in off-session payment: %s', str(e))
        return {
            'status': 'failed',
            'error': e.user_message,
        }

    except stripe.error.AuthenticationRequired as e:
        app_logger.error('Authentication required for off-session payment: %s', str(e))
        return {
            'status': 'failed',
            'error': 'Payment requires authentication',
        }

    except Exception as e:
        app_logger.error('Error in process_off_session_payment: %s', str(e))
        return {
            'status': 'failed',
            'error': str(e),
        }
