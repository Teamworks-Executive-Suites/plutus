#!.venv/bin/python
"""Delete booked_addons rows with a nonsensical quantity.

    .venv/bin/python scripts/fix_bad_addon_quantities.py            # list them
    .venv/bin/python scripts/fix_bad_addon_quantities.py --delete   # remove them

A row at or below zero is not something a guest chose. They were produced by an
old add-on counter that decremented past zero and then wrote the negative value
into a freshly created row, leaving an add-on highlighted and priced on a booking
with no way to remove it. The counter now clamps at both ends, so this cleans up
what the old code left rather than something that recurs.

Two steps on purpose: it deletes from production Firestore, so it prints what it
found and stops unless asked again.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: E402

from app.firebase_setup import db  # noqa: E402


def main() -> int:
    delete = '--delete' in sys.argv

    bad = [
        doc
        for doc in db.collection('booked_addons')
        .where(filter=FieldFilter('setQuantity', '<=', 0))
        .get()
        # The placeholder row written at trip creation is meant to sit at zero.
        if (doc.to_dict() or {}).get('name') != 'initializer'
    ]

    if not bad:
        print('No add-on rows with a bad quantity. Nothing to do.')
        return 0

    print(f'{len(bad)} add-on row(s) with a quantity of zero or less:\n')
    for doc in bad:
        d = doc.to_dict() or {}
        trip = getattr(d.get('tripRef'), 'id', '?')
        print(f'  {doc.id}  {d.get("name")!r}  qty={d.get("setQuantity")}  trip={trip}')

    if not delete:
        print(f'\nNothing deleted. Re-run with --delete to remove these {len(bad)} row(s).')
        return 0

    for doc in bad:
        doc.reference.delete()
    print(f'\nDeleted {len(bad)} row(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
