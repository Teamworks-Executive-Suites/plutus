#!.venv/bin/python
"""Delete bookings made by a test account.

    .venv/bin/python scripts/purge_test_bookings.py            # list them
    .venv/bin/python scripts/purge_test_bookings.py --delete   # remove them

Trips written by an account in teamworks/lib/backend/test_accounts.dart carry
`isTest: true`. They are already ignored when working out availability, so they
never take a room off sale — this is housekeeping, not damage control.

Deliberately two steps. It deletes from production Firestore, so it prints what
it found and stops unless you ask again with --delete. It will only ever touch
documents carrying the flag; a trip without it is somebody's real booking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoneinfo import ZoneInfo  # noqa: E402

from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: E402

from app.firebase_setup import db  # noqa: E402

LA = ZoneInfo('America/Los_Angeles')


def find_test_trips():
    return list(
        db.collection('trips').where(filter=FieldFilter('isTest', '==', True)).get()
    )


def addons_for(trip_ref):
    return list(
        db.collection('booked_addons')
        .where(filter=FieldFilter('tripRef', '==', trip_ref))
        .get()
    )


def main() -> int:
    delete = '--delete' in sys.argv
    trips = find_test_trips()

    if not trips:
        print('No test bookings found. Nothing to do.')
        return 0

    print(f'{len(trips)} test booking(s):\n')
    total_addons = 0
    for t in trips:
        d = t.to_dict() or {}
        begin, end = d.get('tripBeginDateTime'), d.get('tripEndDateTime')
        when = (
            f'{begin.astimezone(LA):%Y-%m-%d %H:%M}-{end.astimezone(LA):%H:%M}'
            if begin and end
            else 'no dates (abandoned before a time was picked)'
        )
        addons = addons_for(t.reference)
        total_addons += len(addons)
        flags = [k for k in ('upcoming', 'complete', 'cancelTrip') if d.get(k)]
        print(f'  {t.id}  {when}  guests={d.get("guests")}  {" ".join(flags) or "-"}')
        if addons:
            print(f'      + {len(addons)} booked add-on row(s)')

    if not delete:
        print(f'\nNothing deleted. Re-run with --delete to remove these '
              f'{len(trips)} trip(s) and {total_addons} add-on row(s).')
        return 0

    for t in trips:
        for a in addons_for(t.reference):
            a.reference.delete()
        for tx in db.collection('transactions').where(filter=FieldFilter('tripRef', '==', t.reference)).get():
            tx.reference.delete()
        t.reference.delete()
    print(f'\nDeleted {len(trips)} trip(s) and {total_addons} add-on row(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
