import logging

app_logger = logging.getLogger('plutus.auto')


def trip_document_id(trip_ref):
    """Return the bare `trips/` document id for a stored `tripRef` value.

    `Transaction.tripRef` is declared `str` in models.py, but production data holds a
    DocumentReference on the large majority of transactions and a 'trips/<id>' path
    string on the rest. Neither can be handed to `.document()` — a DocumentReference
    raises TypeError and a path string raises ValueError ("A document must have an even
    number of path elements") — so every caller must normalise first.

    Returns None when the value is missing or an unrecognised type, letting the caller
    skip that transaction rather than crash the whole scheduled run.
    """
    if trip_ref is None:
        return None
    if hasattr(trip_ref, 'id'):
        return trip_ref.id
    if isinstance(trip_ref, str) and trip_ref:
        return trip_ref.rsplit('/', 1)[-1]
    return None
