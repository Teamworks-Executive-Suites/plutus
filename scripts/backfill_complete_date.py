"""Backfill completeDate on trips that were marked complete before the field existed.

545 trips carry `complete: True` with no `completeDate`. They all end between April 2024
and May 2025, and nothing has produced one since — `auto_complete_and_notify` sets both
fields together, and the Flutter app never sets `complete` at all. So this is legacy
data, not an ongoing bug, and a one-off backfill closes it permanently.

Why it matters beyond tidiness: the escrow release gates on

    complete_date and (now - complete_date).days >= 10

so a trip with no completeDate can never release its escrow, however old it is. One such
trip is holding $105.75 today. Any future trip in this state would be stuck the same way.

completeDate is set to tripEndDateTime — when the booking actually ended, which is what
the field means. Every affected trip ended over a year ago, so all of them clear the
10-day hold either way; the choice of value cannot change any refund or release outcome.

Four trips have no tripEndDateTime and are skipped rather than guessed at.

Every write carries `completeDateBackfilled: True` so this is reversible.

Usage:
    cd /path/to/plutus
    python scripts/backfill_complete_date.py --dry-run   # inspect first
    python scripts/backfill_complete_date.py
"""

import sys

sys.path.insert(0, '.')
from app.firebase_setup import db  # noqa: E402

DRY_RUN = '--dry-run' in sys.argv
MIGRATION_MARKER = 'backfill_complete_date'


def main():
    to_fix = []
    skipped = []

    for trip in db.collection('trips').stream():
        data = trip.to_dict() or {}
        if not data.get('complete') or data.get('completeDate'):
            continue
        end = data.get('tripEndDateTime')
        if not end:
            skipped.append(trip.id)
            continue
        to_fix.append((trip.reference, trip.id, end))

    print(f'trips complete with no completeDate: {len(to_fix) + len(skipped)}')
    print(f'  backfillable from tripEndDateTime: {len(to_fix)}')
    print(f'  skipped, no tripEndDateTime:       {len(skipped)} {skipped}')

    # Show the ones that actually unblock money.
    escrowed_trip_ids = set()
    for txn in db.collection('transactions').stream():
        d = txn.to_dict() or {}
        if d.get('status') != 'in_escrow':
            continue
        ref = d.get('tripRef')
        tid = getattr(ref, 'id', None) or (ref.rsplit('/', 1)[-1] if isinstance(ref, str) else None)
        if tid:
            escrowed_trip_ids.add(tid)

    unblocks = [(tid, end) for _, tid, end in to_fix if tid in escrowed_trip_ids]
    print(f'\nof those, holding escrowed transactions: {len(unblocks)}')
    for tid, end in unblocks:
        print(f'   trip {tid} -> completeDate {end}')

    if DRY_RUN:
        print('\nDRY RUN — nothing written.')
        return

    for ref, tid, end in to_fix:
        ref.update({'completeDate': end, 'completeDateBackfilled': True, 'migratedBy': MIGRATION_MARKER})
    print(f'\nUpdated {len(to_fix)} trips. Reverse with completeDateBackfilled == True.')


if __name__ == '__main__':
    main()
