import logging

from dotenv import load_dotenv

from app.settings import Settings

load_dotenv()

settings = Settings()


app_logger = logging.getLogger('plutus.startup')


def document_id(ref):
    """Return the bare document id for a stored Firestore reference field.

    Reference fields in this schema are declared `str` in models.py but hold three
    different shapes in practice: a DocumentReference, a 'collection/<id>' path string,
    or a bare id. Passing them on unchanged breaks in different ways — `.document()`
    raises TypeError on a DocumentReference and ValueError on a path string, while the
    `ref.split('/')[1]` idiom raises AttributeError on a DocumentReference and IndexError
    on a bare id.

    Returns None when the value is missing or an unrecognised type.
    """
    if ref is None:
        return None
    if hasattr(ref, 'id'):
        return ref.id
    if isinstance(ref, str) and ref:
        return ref.rsplit('/', 1)[-1]
    return None


def snapshot_field(snapshot, name, default=None):
    """Read an optional field from a DocumentSnapshot without raising.

    DocumentSnapshot.get() raises KeyError when the field is absent from a document
    that exists, which is the wrong behaviour for a field that is legitimately
    optional. `stripeAccountID` is absent on every user who has never onboarded to
    Stripe Connect — including the platform user, which is precisely the case the
    settle-in-place branch exists to handle. Reading it with .get() therefore killed
    the whole escrow run on its first eligible row.
    """
    if snapshot is None or not getattr(snapshot, 'exists', False):
        return default
    return (snapshot.to_dict() or {}).get(name, default)
