"""
One-off migration settling escrowed host transactions that belong to test properties.

The escrow release has never run. When it does, the only real money it would move is
$1.05 of Stripe transfers arising from bookings against test offices — trips costing
$2-$3, booked by the team's own accounts. Those should not produce transfers.

Nothing in the schema marks test data: trips have no `isTestBooking`, properties have
no `isTestProperty`, and `isTestAccount` is set on only a handful of users and not
consistently. So the test properties are listed explicitly here, by id, rather than by
matching on their names — a name match would be a live rule inside a money path and
would sweep up any future property that happens to contain "test".

These rows are marked `completed` so they leave the escrow queue without a transfer.
That is a deliberate choice: no money was owed in reality, and the alternative (leaving
them escrowed forever) keeps re-presenting them to every future run.

Usage:
    cd /path/to/plutus
    python scripts/settle_test_property_escrow.py --dry-run   # inspect first
    python scripts/settle_test_property_escrow.py
"""

import sys

# Add parent dir so we can import app modules
sys.path.insert(0, '.')
from app.firebase_setup import db  # noqa: E402
from app.models import ActorRole, Status  # noqa: E402
from app.utils import document_id  # noqa: E402

DRY_RUN = '--dry-run' in sys.argv

MIGRATION_MARKER = 'settle_test_property_escrow'

# Verified by inspection on 10 Aug 2026. The expected name is asserted before any write,
# so if an id is ever reused for a real property this refuses to run rather than settling
# real money silently.
TEST_PROPERTIES = {
    '9Ty3kblcuIuN9DjJP8Wn': 'test office ',
    'TBaeZ2Oru0q2L8j5IjcT': 'Test Office ',
    'XXKz39tWhUeDU6Pzia9e': 'Cooper Test Office',
}


def verify_test_properties():
    """Refuse to run if a listed property is missing or no longer looks like test data."""
    for property_id, expected_name in TEST_PROPERTIES.items():
        doc = db.collection('properties').document(property_id).get()
        if not doc.exists:
            raise SystemExit(f'ABORT: property {property_id} no longer exists')
        actual = (doc.to_dict() or {}).get('propertyName')
        if actual != expected_name:
            raise SystemExit(f'ABORT: property {property_id} is named {actual!r}, expected {expected_name!r}')
        print(f'  verified {property_id} = {actual!r}')


def settle_test_property_escrow():
    print('Verifying the test properties are still what we think they are:')
    verify_test_properties()

    trips = {t.id: (t.to_dict() or {}) for t in db.collection('trips').stream()}

    settled = 0
    settled_cents = 0
    other_roles = 0

    print('\nEscrowed transactions on test properties:')
    for doc in db.collection('transactions').stream():
        data = doc.to_dict() or {}
        if str(data.get('status')) != Status.in_escrow:
            continue

        trip = trips.get(document_id(data.get('tripRef')))
        if not trip or document_id(trip.get('propertyRef')) not in TEST_PROPERTIES:
            continue

        if str(data.get('receiverRole')) != ActorRole.host:
            # Reported but untouched: only host-side rows drive transfers.
            print(f'  - {doc.id}: receiverRole={data.get("receiverRole")}, left alone')
            other_roles += 1
            continue

        cents = data.get('hostFeeCents') or 0
        print(f'  ! {doc.id}: settling ${cents / 100:,.2f} (receiver {document_id(data.get("receiverRef"))})')
        settled += 1
        settled_cents += cents

        if not DRY_RUN:
            doc.reference.update(
                {
                    'status': Status.completed,
                    'statusBeforeMigration': str(data.get('status')),
                    'settledReason': 'test property booking; no transfer made',
                    'migratedBy': MIGRATION_MARKER,
                }
            )

    suffix = ' (dry run, nothing written)' if DRY_RUN else ''
    print('\n--- summary ---')
    print(f'settled without transfer: {settled}{suffix}   ${settled_cents / 100:,.2f}')
    print(f'non-host escrow rows on test properties, untouched: {other_roles}')


if __name__ == '__main__':
    if DRY_RUN:
        print('DRY RUN — no writes will be made\n')
    settle_test_property_escrow()
