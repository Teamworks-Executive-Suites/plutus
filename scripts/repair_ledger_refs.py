"""Repair malformed reference strings in the `transactions` ledger.

DRY RUN BY DEFAULT. Pass --apply to write.

## Why these rows exist

`Transaction.actorRef` / `receiverRef` / `tripRef` are declared `str` and were
written by three different code paths that disagreed about the shape. Two of
those paths were broken and are now fixed (`user_ref_path`), but the rows they
already wrote are still there, and they match no query of any shape — which is
why refunds were unreadable to the very guests they belonged to.

`isOwner()` in firestore.rules now accepts BOTH a DocumentReference and the
string `users/<uid>`, so repairing a row to the canonical string form is what
makes it readable by its owner.

## What it will and will not touch

Repaired, and only after PROVING the target exists:

  * a bare uid              'y1ms…'    -> 'users/y1ms…'   (verified in `users`)
  * the platform literal    'platform' -> 'users/<platform_user_id>'

Left alone and REPORTED, because the original value is unrecoverable from the
row or because repairing it would be a guess:

  * 'users/'                      the uid is simply gone
  * 'users/<DocumentReference …>' an f-string captured a repr, not a path
  * an id that resolves to a PROPERTY rather than a user — a receiver that is
    not a person is a different bug, and quietly rewriting it would hide it

Nothing here invents an identity. A row it cannot prove, it does not touch.
"""

import argparse
import re
import sys

sys.path.insert(0, '.')

from app.firebase_setup import db  # noqa: E402
from app.utils import settings  # noqa: E402

REF_FIELDS = ('actorRef', 'receiverRef', 'tripRef')

# The shape everything should be: 'users/<id>' or 'trips/<id>'.
CANONICAL = re.compile(r'^(users|trips)/[A-Za-z0-9_-]{6,}$')
BARE_ID = re.compile(r'^[A-Za-z0-9_-]{6,}$')

COLLECTION_FOR = {'actorRef': 'users', 'receiverRef': 'users', 'tripRef': 'trips'}

# Naive de-pluralising turns 'properties' into 'propertie'.
SINGULAR = {'users': 'user', 'trips': 'trip', 'properties': 'property'}


def proposed(field, value):
    """What this value should become, or (None, reason) if it must not be touched."""
    if not isinstance(value, str):
        return None, None                      # a DocumentReference is fine as it is
    if CANONICAL.match(value):
        return None, None                      # already correct

    want = COLLECTION_FOR[field]

    if value == 'platform':
        return f'users/{settings.platform_user_id}', None

    if value.endswith('/') or 'DocumentReference' in value:
        return None, 'original id is unrecoverable from the row'

    if BARE_ID.match(value):
        # Prove it before rewriting it.
        if db.collection(want).document(value).get().exists:
            return f'{want}/{value}', None
        for other in ('users', 'trips', 'properties'):
            if other != want and db.collection(other).document(value).get().exists:
                return None, f'id resolves to a {SINGULAR[other]}, not a {SINGULAR[want]}'
        return None, 'id resolves to nothing'

    return None, 'unrecognised shape'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the repairs (default: dry run)')
    ap.add_argument('--limit', type=int, default=5000)
    args = ap.parse_args()

    repairs, skipped, scanned = [], [], 0

    for doc in db.collection('transactions').limit(args.limit).stream():
        scanned += 1
        data = doc.to_dict() or {}
        for field in REF_FIELDS:
            new, reason = proposed(field, data.get(field))
            if new:
                repairs.append((doc.id, field, data[field], new))
            elif reason:
                skipped.append((doc.id, field, data.get(field), reason))

    print(f'scanned {scanned} transactions\n')

    print(f'{len(repairs)} repairable:')
    for doc_id, field, old, new in repairs:
        print(f'  {doc_id[:14]:<15} {field:<12} {old!r:<34} -> {new!r}')

    print(f'\n{len(skipped)} left alone (needs a human):')
    for doc_id, field, old, reason in skipped:
        print(f'  {doc_id[:14]:<15} {field:<12} {str(old)[:44]!r:<46} {reason}')

    if not args.apply:
        print('\nDRY RUN — nothing written. Re-run with --apply to make these changes.')
        return

    for doc_id, field, _old, new in repairs:
        db.collection('transactions').document(doc_id).update({field: new})
    print(f'\napplied {len(repairs)} repairs')


if __name__ == '__main__':
    main()
