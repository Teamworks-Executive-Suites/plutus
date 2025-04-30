import os

import logfire
import stripe

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db
from app.models import Status

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


def process_platform_payout():
    with logfire.span('process_platform_payout'):
        app_logger.info('Starting task to process platform payout')

        # Query all transactions excluding those in escrow
        transactions_ref = db.collection('transactions').where('status', '!=', Status.in_escrow).stream()

        total_balance = 0
        transaction_ids = []

        for transaction in transactions_ref:
            total_balance += transaction.get('netFeeCents', 0)
            transaction_ids.append(transaction.id)

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
