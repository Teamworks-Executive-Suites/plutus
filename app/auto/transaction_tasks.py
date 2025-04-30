import os

import logfire
import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db
from app.models import ActorRole, Status, TransactionType
from app.pay.tasks import calculate_fees
from app.utils import settings

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


def process_transactions():
    with logfire.span('process_transactions'):
        app_logger.info('Starting cron job to process transactions in escrow')

        transactions_ref = (
            db.collection('transactions').where(filter=FieldFilter('status', '==', Status.in_escrow)).stream()
        )

        processed_trip_refs = set()

        for transaction in transactions_ref:
            trip_ref = transaction.get('tripRef')

            if trip_ref in processed_trip_refs:
                continue

            trip = db.collection('trips').document(trip_ref).get()

            if trip.exists and trip.get('complete', False):
                complete_date = trip.get('completeDate')
                if complete_date and (current_time - complete_date).days >= 10:
                    host_transactions_ref = (
                        db.collection('transactions')
                        .where(filter=FieldFilter('tripRef', '==', trip_ref))
                        .where(filter=FieldFilter('receiverRole', '==', ActorRole.host))
                        .stream()
                    )

                    refund_transactions_ref = (
                        db.collection('transactions')
                        .where(filter=FieldFilter('tripRef', '==', trip_ref))
                        .where(filter=FieldFilter('type', '==', TransactionType.refund))
                        .stream()
                    )

                    host_transactions = list(host_transactions_ref)
                    refund_transactions = list(refund_transactions_ref)

                    if not refund_transactions:
                        for host_transaction in host_transactions:
                            receiver_ref = host_transaction.get('receiverRef')
                            user = db.collection('users').document(receiver_ref.split('/')[1]).get()
                            stripe_account_id = user.get('stripeAccountID')

                            if stripe_account_id:
                                try:
                                    transfer = stripe.Transfer.create(
                                        amount=host_transaction.get('hostFeeCents'),
                                        currency='usd',
                                        destination=stripe_account_id,
                                        transfer_group=trip_ref,
                                    )
                                    app_logger.info('Transfer created: %s', transfer)
                                    host_transaction.reference.update(
                                        {'status': Status.completed, 'transferId': transfer.id}
                                    )
                                except Exception as e:
                                    app_logger.error('Failed to create transfer: %s', str(e))
                            elif host_transaction.get('receiverRef') == f'users/{settings.platform_user_id}':
                                host_transaction.reference.update({'status': Status.completed})
                            else:
                                app_logger.error(
                                    'No Stripe account ID for user %s, unable to process transfer,',
                                    host_transaction.get('receiverRef'),
                                )

                    else:
                        total_owed = sum(t.get('grossFeeCents') for t in host_transactions) - sum(
                            t.get('grossFeeCents') for t in refund_transactions
                        )

                        host_fee, guest_fee, net_fee = calculate_fees(total_owed)

                        new_transaction_data = {
                            'actorRef': transaction.get('actorRef'),
                            'actorRole': transaction.get('actorRole'),
                            'receiverRef': host_transactions[0].get('receiverRef'),
                            'receiverRole': ActorRole.host,
                            'status': Status.in_escrow,
                            'type': TransactionType.transfer,
                            'grossFeeCents': total_owed,
                            'guestFeeCents': guest_fee,
                            'hostFeeCents': host_fee,
                            'netFeeCents': net_fee,
                            'tripRef': trip_ref,
                            'refundedAmountCents': 0,
                            'paymentIntentIds': [],
                            'mergedTransactions': [t.id for t in host_transactions],
                        }
                        new_transaction_ref = db.collection('transactions').add(new_transaction_data)[1]

                        for t in host_transactions:
                            t.reference.update({'status': Status.merged})

                        receiver_ref = new_transaction_data['receiverRef']
                        user = db.collection('users').document(receiver_ref.split('/')[1]).get()
                        stripe_account_id = user.get('stripeAccountID')

                        if stripe_account_id:
                            try:
                                transfer = stripe.Transfer.create(
                                    amount=new_transaction_data['hostFeeCents'],
                                    currency='usd',
                                    destination=stripe_account_id,
                                    transfer_group=trip_ref,
                                )
                                app_logger.info('Transfer created: %s', transfer)
                                new_transaction_ref.update({'status': Status.completed, 'transferId': transfer.id})
                            except Exception as e:
                                app_logger.error('Failed to create transfer: %s', str(e))

            processed_trip_refs.add(trip_ref)
