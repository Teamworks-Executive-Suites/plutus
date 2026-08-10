"""
One-off migration repairing `receiverRef` on host-role transactions.

Two upstream bugs wrote the wrong receiver, both fixed in code but leaving bad rows:

  * confirmation_widget.dart addressed four of its fourteen "Platform -> Host"
    transfers to `tripDoc.userRef` — the guest who booked — instead of
    `officeDoc.userRef`, the property's owner.
  * plutus process_extra_charge addressed the host transfer to the *property id*,
    which is not a user at all.

It also normalises the stored type. `TransactionsRecord` casts
`snapshotData['receiverRef'] as DocumentReference?`, a hard cast, so a row holding a
string throws in the Flutter app when the transactions list is read. The large
majority of rows already hold a DocumentReference, so that is the target shape.

The correct receiver is the owner of the trip's property, falling back to the trip's
denormalised `host` field — never the trip's `userRef`, which is the guest.

Rows whose trip no longer exists are left completely alone. There is no way to derive
a host for them and voiding them is a business decision, not a migration.

Usage:
    cd /path/to/plutus
    python scripts/fix_host_transaction_receivers.py --dry-run   # inspect first
    python scripts/fix_host_transaction_receivers.py
"""

import sys

# Add parent dir so we can import app modules
sys.path.insert(0, '.')
from app.firebase_setup import db  # noqa: E402
from app.models import ActorRole  # noqa: E402
from app.utils import document_id  # noqa: E402

DRY_RUN = '--dry-run' in sys.argv

# Stamped on every touched document alongside the prior value, so the migration can be
# identified and reversed:
#   for d in db.collection('transactions').where('migratedBy', '==', MIGRATION_MARKER).stream():
#       d.reference.update({'receiverRef': <users/ ref built from receiverRefBeforeMigration>})
MIGRATION_MARKER = 'fix_host_transaction_receivers'


def expected_host_id(trip_data, properties):
    """The property's owner is the source of truth; trip['host'] is the fallback."""
    property_id = document_id(trip_data.get('propertyRef'))
    if property_id and property_id in properties:
        owner_id = document_id(properties[property_id].get('userRef'))
        if owner_id:
            return owner_id
    return document_id(trip_data.get('host'))


def fix_host_transaction_receivers():
    properties = {p.id: (p.to_dict() or {}) for p in db.collection('properties').stream()}
    trips = {t.id: (t.to_dict() or {}) for t in db.collection('trips').stream()}

    reassigned = retyped = already_correct = orphaned = unresolvable = 0
    reassigned_cents = 0

    for doc in db.collection('transactions').stream():
        data = doc.to_dict() or {}
        if str(data.get('receiverRole')) != ActorRole.host:
            continue

        trip_id = document_id(data.get('tripRef'))
        if trip_id not in trips:
            orphaned += 1
            continue

        expected = expected_host_id(trips[trip_id], properties)
        if not expected:
            print(f'  ? {doc.id}: cannot resolve a host for trip {trip_id}, leaving alone')
            unresolvable += 1
            continue

        current = document_id(data.get('receiverRef'))
        stored_as_reference = hasattr(data.get('receiverRef'), 'id')
        cents = data.get('hostFeeCents') or 0

        if current == expected and stored_as_reference:
            already_correct += 1
            continue

        new_ref = db.collection('users').document(expected)

        if current != expected:
            print(
                f'  ! {doc.id}: receiver {current} -> {expected}  '
                f'(${cents / 100:,.2f}, status={data.get("status")})'
            )
            reassigned += 1
            reassigned_cents += cents
        else:
            # Right person, wrong type: a string the Flutter client cannot cast.
            print(f'  ~ {doc.id}: retyping receiver {current} to a DocumentReference')
            retyped += 1

        if not DRY_RUN:
            # Record what was there before. These are money records and this migration
            # has no natural inverse, so keep the prior value on the document itself:
            # rollback is then a query for the marker rather than a restore from backup.
            doc.reference.update(
                {
                    'receiverRef': new_ref,
                    'receiverRefBeforeMigration': str(current),
                    'migratedBy': MIGRATION_MARKER,
                }
            )

    suffix = ' (dry run, nothing written)' if DRY_RUN else ''
    print('\n--- summary ---')
    print(f'reassigned to correct host:  {reassigned}{suffix}   ${reassigned_cents / 100:,.2f}')
    print(f'retyped to DocumentReference:{retyped}{suffix}')
    print(f'already correct:             {already_correct}')
    print(f'trip no longer exists:       {orphaned}  (left alone — needs a business decision)')
    print(f'host unresolvable:           {unresolvable}')


if __name__ == '__main__':
    if DRY_RUN:
        print('DRY RUN — no writes will be made\n')
    fix_host_transaction_receivers()
