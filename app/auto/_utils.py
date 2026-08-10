import logging

app_logger = logging.getLogger('plutus.auto')


def document_id(ref):
    """Return the bare document id for a stored Firestore reference field.

    `Transaction.tripRef` and `Transaction.receiverRef` are both declared `str` in
    models.py, but production data holds three different shapes for each:

        tripRef      DocumentReference 297 / 'trips/<id>'  22 / bare id   0   (of 319)
        receiverRef  DocumentReference 297 / 'users/<id>'   8 / bare id  14   (of 319)

    Passing these on unchanged breaks in different ways. `.document()` raises TypeError
    on a DocumentReference and ValueError on a path string, while the old
    `ref.split('/')[1]` idiom raises AttributeError on a DocumentReference and
    IndexError on a bare id — none of them inside a try, so a single such document
    killed the whole scheduled run.

    Returns None when the value is missing or an unrecognised type, so callers can skip
    that transaction instead of crashing.
    """
    if ref is None:
        return None
    if hasattr(ref, 'id'):
        return ref.id
    if isinstance(ref, str) and ref:
        return ref.rsplit('/', 1)[-1]
    return None
