import logfire
import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db
from app.models import Status


def process_platform_payout():
    with logfire.span('process_platform_payout'):
        app_logger.info('Starting task to process platform payout')

        try:
            # Query all transactions excluding those in escrow
            transactions_ref = (
                db.collection('transactions').where(filter=FieldFilter('status', '!=', Status.in_escrow)).stream()
            )

            processed_trip_refs = set()
            total_balance = 0
            transaction_ids = []

            for transaction in transactions_ref:
                transaction_doc = db.collection('transactions').document(transaction.id).get()
                transaction_data = transaction_doc.to_dict()
                trip_ref_obj = transaction_doc.get('tripRef')
                if hasattr(trip_ref_obj, 'id'):
                    trip_ref = trip_ref_obj.id
                else:
                    trip_ref = trip_ref_obj

                if not trip_ref or trip_ref in processed_trip_refs:
                    continue

                trip = db.collection('trips').document(trip_ref).get()

                if trip.exists:
                    try:
                        net_fee_cents = transaction_data.get('netFeeCents', 0)
                        total_balance += net_fee_cents
                        transaction_ids.append(transaction_doc.id)
                        processed_trip_refs.add(trip_ref)
                    except Exception as e:
                        app_logger.error('Error processing transaction %s: %s', transaction.id, str(e))

            if total_balance > 0:
                try:
                    # Create a Stripe payout
                    payout = stripe.Payout.create(
                        amount=total_balance,
                        currency='usd',
                        description='Platform payout for remaining balance',
                    )
                    app_logger.info('Payout created: %s', payout)

                    # Log the payout in Firestore
                    payout_data = {
                        'status': Status.completed,
                        'amountCents': total_balance,
                        'processedAt': current_time,
                        'stripePayoutId': payout.id,
                        'transactionIds': transaction_ids,
                    }
                    db.collection('payouts').add(payout_data)

                except Exception as e:
                    app_logger.error('Failed to create platform payout: %s', str(e))
            else:
                app_logger.info('No balance available for platform payout')

        except Exception as e:
            app_logger.error('Error during platform payout processing: %s', str(e))
