import logging

from google.cloud.firestore_v1 import FieldFilter
from mockfirestore.collection import CollectionReference
from mockfirestore.document import DocumentReference
from mockfirestore.query import Query

logger = logging.getLogger(__name__)


def enable_field_filter_support():
    """Teach MockFirestore the ``where(filter=FieldFilter(...))`` form.

    mock-firestore 0.11.0 only implements the positional ``where(field, op, value)``
    signature, but the production code uses the keyword ``filter=`` form that real
    Firestore requires. Without this shim every query under test raises TypeError.

    Idempotent, so test modules can call it at import time without coordinating.
    """
    for cls in (CollectionReference, Query):
        original = cls.where
        if getattr(original, '_accepts_field_filter', False):
            continue

        def where(self, field=None, op=None, value=None, filter=None, _original=original):
            if filter is not None:
                field, op, value = filter.field_path, filter.op_string, filter.value
            return _original(self, field, op, value)

        where._accepts_field_filter = True
        cls.where = where


def enable_document_reference_equality():
    """Give MockFirestore's DocumentReference the value equality the real one has.

    ``google.cloud.firestore_v1``'s DocumentReference compares by client and path, so a
    query filtering on a DocumentReference field matches a reference read back out of the
    store. mock-firestore 0.11.0 defines no ``__eq__`` at all and falls back to identity,
    so the same document read twice compares unequal and such a query silently returns
    nothing — which does not reflect production behaviour.

    Idempotent, so test modules can call it at import time without coordinating.
    """
    if '__eq__' in DocumentReference.__dict__:
        return

    def __eq__(self, other):
        if isinstance(other, DocumentReference):
            return self._path == other._path
        return NotImplemented

    DocumentReference.__eq__ = __eq__
    DocumentReference.__hash__ = lambda self: hash(tuple(self._path))


__all__ = [
    'FieldFilter',
    'enable_document_reference_equality',
    'enable_field_filter_support',
    'logger',
]
