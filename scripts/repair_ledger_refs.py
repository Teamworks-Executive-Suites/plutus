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

Nothing here invents an identity. A row it cannot prove, it does not touch.

## --resolve-property-owners

One row type IS recoverable but is held back behind its own flag: a
`receiverRef` holding a PROPERTY id, written by the pre-fix extra-charge path,
which stored the property instead of the property's owner. `transaction_tasks`
logs 'unusable receiverRef, skipping' for it, so the host is never paid.

The repair uses the same derivation the FIXED writer now uses
(`resolve_host_user_ref`: property -> userRef -> owner uid), and still proves
the owner is a real user before addressing money to them. It is opt-in because
it changes WHO a row pays rather than how that person is spelled -- a shape fix
is arithmetic, this one is a decision.
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


def property_owner_id(property_id):
    """The uid that owns a property, or None.

    Same derivation `resolve_host_user_ref` in app/pay/tasks.py now uses: the
    property's `userRef` is the source of truth for who hosts a booking. That
    function is the fixed version of the code that wrote the broken rows, so
    repairing with it reproduces what the writer would emit today.
    """
    prop = db.collection('properties').document(property_id).get()
    if not prop.exists:
        return None
    owner = (prop.to_dict() or {}).get('userRef')
    owner_id = getattr(owner, 'id', None) or (
        owner.rsplit('/', 1)[-1] if isinstance(owner, str) else None)
    if not owner_id:
        return None
    # Prove the owner is a real user before addressing money to them.
    return owner_id if db.collection('users').document(owner_id).get().exists else None


def proposed(field, value, resolve_property_owners=False):
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
                # A receiverRef holding a PROPERTY id is the pre-fix extra-charge
                # writer: it stored the property instead of the property's owner.
                # The identity is recoverable, but recovering it is a different
                # act from fixing a prefix -- it decides WHO gets paid -- so it
                # stays behind its own flag rather than riding along with the
                # shape repairs.
                if (other == 'properties' and want == 'users'
                        and field == 'receiverRef' and resolve_property_owners):
                    owner_id = property_owner_id(value)
                    if owner_id:
                        return f'users/{owner_id}', None
                    return None, 'property has no resolvable owner'
                return None, f'id resolves to a {SINGULAR[other]}, not a {SINGULAR[want]}'
        return None, 'id resolves to nothing'

    return None, 'unrecognised shape'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the repairs (default: dry run)')
    ap.add_argument('--limit', type=int, default=5000)
    ap.add_argument(
        '--resolve-property-owners', action='store_true',
        help="also repair a receiverRef holding a PROPERTY id, by looking up that "
             "property's owner. Off by default: this decides who gets paid, which "
             "is a different act from fixing a prefix.")
    args = ap.parse_args()

    repairs, skipped, scanned = [], [], 0

    for doc in db.collection('transactions').limit(args.limit).stream():
        scanned += 1
        data = doc.to_dict() or {}
        for field in REF_FIELDS:
            new, reason = proposed(field, data.get(field), args.resolve_property_owners)
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
