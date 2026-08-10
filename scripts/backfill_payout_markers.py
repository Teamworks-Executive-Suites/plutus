"""
One-off script to backfill `paidOut` markers on historical transactions.

MUST be run BEFORE deploying the payout-idempotency fix.

`process_platform_payout` previously had no idempotency guard: it selected every
transaction with `status != in_escrow` and paid the total out again on every hourly
run. The fix adds a `paidOut` marker and skips transactions carrying it.

Because no historical transaction has that field, the first run after deploy would
select the entire history and issue one enormous payout. This script closes that gap
by marking every pre-existing settled transaction as already paid out — which is
accurate, since the buggy job has been paying them out repeatedly for months.

Transactions still `in_escrow` are left untouched: they have not been paid out and
must stay eligible once they settle.

Usage:
    cd /path/to/plutus
    python scripts/backfill_payout_markers.py --dry-run   # inspect first
    python scripts/backfill_payout_markers.py
"""

import sys

# Add parent dir so we can import app modules
sys.path.insert(0, '.')
from app.firebase_setup import db  # noqa: E402
from app.models import Status  # noqa: E402

DRY_RUN = '--dry-run' in sys.argv

BACKFILL_MARKER = 'backfill-pre-idempotency'


def backfill_payout_markers():
    # Read every transaction rather than filtering server-side: an inequality filter
    # would silently drop documents that have no `status` field at all, and those
    # still need a decision.
    transactions = list(db.collection('transactions').stream())

    marked = 0
    skipped_escrow = 0
    skipped_already_marked = 0
    skipped_no_status = 0

    for transaction in transactions:
        data = transaction.to_dict() or {}

        if data.get('paidOut') is not None:
            skipped_already_marked += 1
            continue

        status = data.get('status')
        if status is None:
            print(f'  ! {transaction.id}: no status field, leaving alone for manual review')
            skipped_no_status += 1
            continue

        if status == Status.in_escrow:
            skipped_escrow += 1
            continue

        if DRY_RUN:
            print(f'  would mark {transaction.id} (status={status}, netFeeCents={data.get("netFeeCents")})')
        else:
            transaction.reference.update({'paidOut': True, 'payoutId': BACKFILL_MARKER})
        marked += 1

    print('\n--- summary ---')
    print(f'total transactions:        {len(transactions)}')
    print(f'marked as paid out:        {marked}{" (dry run, nothing written)" if DRY_RUN else ""}')
    print(f'left in escrow:            {skipped_escrow}')
    print(f'already had a marker:      {skipped_already_marked}')
    print(f'no status, needs review:   {skipped_no_status}')


if __name__ == '__main__':
    if DRY_RUN:
        print('DRY RUN — no writes will be made\n')
    backfill_payout_markers()
