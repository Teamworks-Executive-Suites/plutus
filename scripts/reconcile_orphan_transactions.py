"""
Read-only reconciliation of escrowed host transactions whose trip no longer exists.

52 host-role transactions ($4,031.21) reference trips that have been deleted — most
likely by the booking-edit and refund paths, which delete the trip document without
removing the transactions that point at it. No host can be derived for them, so they
sit in escrow forever and the release job skips them.

Deciding what to do with them needs to know whether real money ever moved. Firestore
has lost the trip, but Stripe still has the charge history, so this script walks each
missing trip's payment intents and reports what actually happened.

WRITES NOTHING. It only reads Firestore and Stripe.

REQUIRES A LIVE STRIPE KEY. The repository .env carries a test-mode key while the
Firestore credentials point at production, so a test key reports "No such
payment_intent" for every production intent — which reads exactly like "no money was
ever charged" and would justify voiding rows that represent real payments. The script
refuses to run in that combination unless you force it.

Usage:
    cd /path/to/plutus
    STRIPE_SECRET_KEY=sk_live_... python scripts/reconcile_orphan_transactions.py
    # --allow-test-key only to prove the mismatch; results are meaningless
"""

import os
import sys
from collections import defaultdict

import stripe

# Add parent dir so we can import app modules
sys.path.insert(0, '.')
from app.firebase_setup import db  # noqa: E402
from app.utils import document_id  # noqa: E402  (import also triggers load_dotenv)

ALLOW_TEST_KEY = '--allow-test-key' in sys.argv

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


def check_key_mode():
    key = stripe.api_key or ''
    if key.startswith('sk_live'):
        return
    mode = 'test-mode' if key.startswith('sk_test') else 'missing/unrecognised'
    if ALLOW_TEST_KEY:
        print(f'WARNING: {mode} Stripe key against production Firestore. Results are meaningless.\n')
        return
    raise SystemExit(
        f'ABORT: Stripe key is {mode}, but the Firestore data is production.\n'
        '       Every lookup would return "No such payment_intent", which is\n'
        '       indistinguishable from "never charged". Re-run with a live key.'
    )


def collect_orphans():
    trip_ids = {t.id for t in db.collection('trips').stream()}
    txns = [(d.id, d.to_dict() or {}) for d in db.collection('transactions').stream()]

    orphan_hosts = [
        (i, x)
        for i, x in txns
        if str(x.get('receiverRole')) == 'host' and document_id(x.get('tripRef')) not in trip_ids
    ]
    orphan_trips = {document_id(x.get('tripRef')) for _, x in orphan_hosts}

    # Payment intents are usually recorded on the client->platform row, not the host row,
    # so gather them from every transaction referencing the same missing trip.
    intents_by_trip = defaultdict(set)
    for i, x in txns:
        trip_id = document_id(x.get('tripRef'))
        if trip_id in orphan_trips:
            intents_by_trip[trip_id].update(x.get('paymentIntentIds') or [])

    return orphan_hosts, intents_by_trip


def describe_intent(intent_id):
    try:
        pi = stripe.PaymentIntent.retrieve(intent_id, expand=['charges'])
    except stripe.error.InvalidRequestError as e:
        return {'id': intent_id, 'verdict': 'NOT FOUND IN STRIPE', 'detail': str(e)[:60]}
    except Exception as e:  # network, auth, rate limit
        return {'id': intent_id, 'verdict': 'LOOKUP FAILED', 'detail': f'{type(e).__name__}: {str(e)[:60]}'}

    refunded = 0
    for charge in stripe.Charge.list(payment_intent=intent_id).auto_paging_iter():
        refunded += charge.amount_refunded

    if pi.status == 'succeeded':
        verdict = (
            'CHARGED, FULLY REFUNDED'
            if refunded >= pi.amount_received
            else ('CHARGED, PARTLY REFUNDED' if refunded else 'CHARGED, NOT REFUNDED')
        )
    else:
        verdict = f'NEVER CHARGED ({pi.status})'

    return {
        'id': intent_id,
        'verdict': verdict,
        'amount': pi.amount,
        'received': pi.amount_received,
        'refunded': refunded,
        'created': pi.created,
    }


def reconcile():
    check_key_mode()
    orphan_hosts, intents_by_trip = collect_orphans()

    print(f'orphan host transactions: {len(orphan_hosts)}')
    print(f'missing trips:            {len(intents_by_trip)}')
    all_intents = sorted({p for s in intents_by_trip.values() for p in s})
    print(f'payment intents to check: {len(all_intents)}\n')

    results = {}
    for intent_id in all_intents:
        results[intent_id] = describe_intent(intent_id)
        r = results[intent_id]
        amount = f'${r.get("received", 0) / 100:,.2f}' if 'received' in r else ''
        print(f'  {intent_id}  {r["verdict"]:26} {amount}')

    print('\n--- per orphan transaction ---')
    tally = defaultdict(lambda: [0, 0])
    for txn_id, data in sorted(orphan_hosts, key=lambda r: -(r[1].get('hostFeeCents') or 0)):
        trip_id = document_id(data.get('tripRef'))
        verdicts = {results[p]['verdict'] for p in intents_by_trip.get(trip_id, set())} or {'NO PAYMENT INTENT'}
        verdict = ' + '.join(sorted(verdicts))
        cents = data.get('hostFeeCents') or 0
        tally[verdict][0] += 1
        tally[verdict][1] += cents
        print(f'  {txn_id}  ${cents / 100:>9,.2f}  trip {trip_id}  {verdict}')

    print('\n--- summary ---')
    for verdict, (count, cents) in sorted(tally.items(), key=lambda kv: -kv[1][1]):
        print(f'  {verdict:34} {count:3} rows   ${cents / 100:>10,.2f}')
    print('\nCHARGED, NOT REFUNDED means a guest really paid and the host side was never')
    print('settled. Those are the ones that must not simply be voided.')


if __name__ == '__main__':
    reconcile()
