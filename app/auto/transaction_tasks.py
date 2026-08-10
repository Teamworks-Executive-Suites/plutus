import os
from datetime import datetime, timezone

import logfire
import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger, document_id
from app.firebase_setup import db
from app.models import ActorRole, Status, TransactionType
from app.pay.tasks import calculate_fees
from app.utils import settings

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


def process_transactions():
    with logfire.span('process_transactions'):
        app_logger.info('Starting cron job to process transactions in escrow')

        # Materialise the stream before counting it: a Firestore stream is a one-shot
        # generator, so logging len(list(...)) on it would leave nothing left to iterate.
        transactions = list(
            db.collection('transactions').where(filter=FieldFilter('status', '==', Status.in_escrow)).stream()
        )
        app_logger.info('Found %d transactions in escrow', len(transactions))

        # Read the clock per run. This task runs hourly inside a long-lived process, so a
        # module-level timestamp would freeze at process start and no trip completed after
        # deploy would ever clear the 10-day hold.
        now = datetime.now(timezone.utc)

        processed_trip_refs = set()

        for transaction in transactions:
            transaction_doc = db.collection('transactions').document(transaction.id).get()
            # Keep the stored value for querying and re-writing, and a normalised id for
            # document lookups and de-duplication. See document_id for why.
            trip_ref = transaction_doc.get('tripRef')
            trip_id = document_id(trip_ref)

            if trip_id is None:
                app_logger.error('Transaction %s has an unusable tripRef, skipping', transaction.id)
                continue

            if trip_id in processed_trip_refs:
                app_logger.info('Skipping already processed trip: %s', trip_id)
                continue

            trip = db.collection('trips').document(trip_id).get()

            if trip.exists and trip.get('complete'):
                trip_data = trip.to_dict()
                complete_date = trip_data.get('completeDate')
                app_logger.info('Checking trip %s, complete_date: %s', trip_id, complete_date)
                if complete_date and (now - complete_date).days >= 10:
                    app_logger.info('Trip %s is complete and eligible for processing', trip_id)

                    # Escrowed only: a trip can carry host transactions that already
                    # transferred, and those must not be paid or merged a second time.
                    host_transactions_ref = (
                        db.collection('transactions')
                        .where(filter=FieldFilter('tripRef', '==', trip_ref))
                        .where(filter=FieldFilter('receiverRole', '==', ActorRole.host))
                        .where(filter=FieldFilter('status', '==', Status.in_escrow))
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

                    app_logger.info(
                        'Host transactions: %d, Refund transactions: %d',
                        len(host_transactions),
                        len(refund_transactions),
                    )

                    if not refund_transactions:
                        for host_transaction in host_transactions:
                            receiver_id = document_id(host_transaction.get('receiverRef'))
                            if receiver_id is None:
                                app_logger.error(
                                    'Transaction %s has an unusable receiverRef, skipping', host_transaction.id
                                )
                                continue

                            user = db.collection('users').document(receiver_id).get()
                            stripe_account_id = user.get('stripeAccountID') if user.exists else None

                            if receiver_id == settings.platform_user_id:
                                # The platform is its own host and holds no Connect account;
                                # there is nothing to transfer, so just settle the row.
                                host_transaction.reference.update({'status': Status.completed})
                            elif stripe_account_id:
                                try:
                                    transfer = stripe.Transfer.create(
                                        amount=host_transaction.get('hostFeeCents'),
                                        currency='usd',
                                        destination=stripe_account_id,
                                        transfer_group=trip_id,
                                    )
                                    app_logger.info('Transfer created: %s', transfer)
                                    host_transaction.reference.update(
                                        {'status': Status.completed, 'transferId': transfer.id}
                                    )
                                except Exception as e:
                                    app_logger.error('Failed to create transfer: %s', str(e))
                            else:
                                app_logger.error(
                                    'No Stripe account ID for user %s, unable to process transfer,',
                                    receiver_id,
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

                        receiver_id = document_id(new_transaction_data['receiverRef'])
                        user = db.collection('users').document(receiver_id).get() if receiver_id else None
                        stripe_account_id = user.get('stripeAccountID') if user and user.exists else None

                        if receiver_id == settings.platform_user_id:
                            new_transaction_ref.update({'status': Status.completed})
                        elif stripe_account_id:
                            try:
                                transfer = stripe.Transfer.create(
                                    amount=new_transaction_data['hostFeeCents'],
                                    currency='usd',
                                    destination=stripe_account_id,
                                    transfer_group=trip_id,
                                )
                                app_logger.info('Transfer created: %s', transfer)
                                new_transaction_ref.update({'status': Status.completed, 'transferId': transfer.id})
                            except Exception as e:
                                app_logger.error('Failed to create transfer: %s', str(e))

            processed_trip_refs.add(trip_id)
