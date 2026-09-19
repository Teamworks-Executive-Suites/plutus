import os
from datetime import datetime, timezone

import logfire
import stripe
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger, document_id
from app.firebase_setup import db, utc_now
from app.models import ActorRole, Status, TransactionType
from app.pay.tasks import calculate_fees
from app.utils import settings, snapshot_field

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')



def cents_from(snapshot, *names):
    """A money field off a transaction snapshot, or 0 if it carries none of them.

    Reads through `to_dict()` on purpose. `DocumentSnapshot.get()` RAISES
    KeyError for a field the document does not have — it does not return None —
    so the common `snapshot.get('x') or 0` blows up on exactly the documents it
    was written to tolerate. MockFirestore returns None instead, which is why
    this never failed in a test.

    Takes several names because the app and Plutus disagree about one: a refund
    row written by the app carries `refundAmountCents`, one written here carries
    `refundedAmountCents`. Both mean the same money.
    """
    data = snapshot.to_dict() or {}
    for name in names:
        value = data.get(name)
        if value:
            return value
    return 0


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

            # A test booking writes the same in_escrow host transaction as a real one,
            # so without this the platform transfers real money to a host for a booking
            # nobody paid for. Checked before the completion branch so it never reaches
            # stripe.Transfer.create at all.
            if trip.exists and (trip.to_dict() or {}).get('isTest'):
                app_logger.info('Skipping test booking %s', trip_id)
                continue

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
                            stripe_account_id = snapshot_field(user, 'stripeAccountID')

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

                    elif not host_transactions:
                        # A refunded trip can have no escrowed host rows left to merge —
                        # they may already have settled, or never existed. There is
                        # nothing to pay and no receiver to derive, so leave it alone
                        # rather than indexing an empty list and killing the whole run.
                        app_logger.info(
                            'Trip %s is refunded with no escrowed host transactions; nothing to merge', trip_id
                        )

                    else:
                        # What the host is owed, less what was actually refunded.
                        #
                        # Two bugs lived in this one expression, and production
                        # has rows proving both.
                        #
                        # 1. It subtracted `grossFeeCents` from the REFUND rows,
                        #    and every refund row carries grossFeeCents 0 — the
                        #    money is in refundedAmountCents (pay/tasks.py:245,
                        #    278, 611). So the subtraction was always zero and a
                        #    refunded booking still paid the host in full. One
                        #    live row has grossFeeCents 0 against
                        #    refundedAmountCents 71200.
                        #
                        # 2. `DocumentSnapshot.get()` RAISES KeyError on a field
                        #    the document does not have; it does not return None,
                        #    so `or 0` never ran. The comment here claimed it
                        #    treated a missing amount as zero. It did not — and
                        #    three live refund rows written by the app have no
                        #    grossFeeCents at all, so this raised and killed the
                        #    whole escrow-release run for every trip after it.
                        #    MockFirestore returns None instead, which is why no
                        #    test caught it.
                        #
                        # Read through to_dict(), where a missing key really is
                        # None. And the app and Plutus disagree on the field
                        # name — refundAmountCents against refundedAmountCents —
                        # so both are read; a refund is a refund whoever wrote it.
                        total_owed = sum(
                            cents_from(t, 'grossFeeCents') for t in host_transactions
                        ) - sum(
                            cents_from(t, 'refundedAmountCents', 'refundAmountCents')
                            for t in refund_transactions
                        )

                        # A refund larger than the escrowed amount would make
                        # this negative and calculate_fees would hand Stripe a
                        # negative transfer. Nothing is owed, not less than
                        # nothing.
                        total_owed = max(total_owed, 0)

                        host_fee, guest_fee, net_fee = calculate_fees(total_owed)

                        # `createdAt` and `processedAt` are not optional.
                        #
                        # Every transaction surface in the app orders by
                        # createdAt, and a Firestore orderBy SKIPS documents
                        # that lack the field — the same trap as an equality
                        # filter. This row replaces the host's escrowed rows
                        # and is the one that carries the real Stripe transfer,
                        # so without them the payout for every refunded trip
                        # would be invisible to the host who received it, while
                        # the rows it superseded are marked `merged` and
                        # filtered out.
                        #
                        # Never fired in production: no transaction currently
                        # carries `mergedTransactions`, so this path has not
                        # run yet. Fixed before it does.
                        new_transaction_data = {
                            'actorRef': transaction.get('actorRef'),
                            'actorRole': transaction.get('actorRole'),
                            'receiverRef': host_transactions[0].get('receiverRef'),
                            'receiverRole': ActorRole.host,
                            'status': Status.in_escrow,
                            'type': TransactionType.transfer,
                            'createdAt': utc_now(),
                            'processedAt': utc_now(),
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
                        stripe_account_id = snapshot_field(user, 'stripeAccountID')

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
