import logging

from google.cloud.firestore_v1 import FieldFilter
from mockfirestore.collection import CollectionReference
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


__all__ = ['FieldFilter', 'enable_field_filter_support', 'logger']
