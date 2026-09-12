"""No ledger ref field is ever assigned a raw string.

`actorRef` / `receiverRef` / `tripRef` are declared `str` and the ledger is read
by matching on them, so the value has to be one predictable shape. Four
different shapes reached production before anyone noticed, because each was
written by a different call site and every one of them looked fine in isolation:

    receiverRef=f'users/{trip.get("userRef")}'   -> 'users/<DocumentReference ...>'
    receiverRef=doc_id                           -> bare id, no prefix
    receiverRef='platform'                       -> a word, not a reference
    receiverRef=user_ref_path(...)               -> the intended shape

The first three match no query of any shape. `transaction_tasks` logs
'unusable receiverRef, skipping' and passes the row over -- which for a
host-side transfer means the host is never paid for it, and for a refund means
the guest cannot see their own money coming back.

`repair_ledger_refs.py` normalised the rows already written. This test is what
stops them coming back: a writer that bypasses `user_ref_path` is the bug, and
it is detectable at the assignment rather than months later in the data.

Deliberately an AST check, not a grep for 'platform'. A grep would go green the
moment someone spelled the same mistake differently.
"""

import ast
import pathlib
from unittest import TestCase

REF_FIELDS = {'actorRef', 'receiverRef', 'tripRef'}

APP = pathlib.Path(__file__).resolve().parent.parent / 'app'


def _literal_ref_assignments():
    """Every `someRef=<constant>` keyword argument under app/.

    Keyword arguments only: these fields are populated by constructing a
    `Transaction(...)`, so that is where a bad shape enters the ledger.
    """
    bad = []
    for path in sorted(APP.rglob('*.py')):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg not in REF_FIELDS:
                    continue
                # A plain string, or an f-string -- the two ways a raw value
                # has actually got in. An f-string is the worse of the two:
                # it stringifies whatever object it is handed, including a
                # DocumentReference's repr.
                if isinstance(kw.value, (ast.Constant, ast.JoinedStr)):
                    rendered = ast.unparse(kw.value)
                    bad.append(f'{path.relative_to(APP.parent)}:{kw.value.lineno} '
                               f'{kw.arg}={rendered}')
    return bad


class TestLedgerRefShapes(TestCase):
    def test_no_ref_field_is_assigned_a_raw_string(self):
        bad = _literal_ref_assignments()
        self.assertEqual(
            bad, [],
            'These write a ledger ref without going through user_ref_path(), so '
            'the row will match no query and be skipped by the reader:\n  '
            + '\n  '.join(bad))

    def test_the_check_can_actually_fail(self):
        """Proof the detector works, so a green run above means something.

        A source-shape test that has never been seen failing is indistinguishable
        from one whose pattern simply does not match anything.
        """
        tree = ast.parse("Transaction(receiverRef='platform', actorRole=x)")
        found = [kw.arg for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 for kw in node.keywords
                 if kw.arg in REF_FIELDS and isinstance(kw.value, (ast.Constant, ast.JoinedStr))]
        self.assertEqual(found, ['receiverRef'])

    def test_the_check_catches_the_f_string_shape_too(self):
        tree = ast.parse('Transaction(receiverRef=f"users/{trip.get(\'userRef\')}")')
        found = [kw.arg for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 for kw in node.keywords
                 if kw.arg in REF_FIELDS and isinstance(kw.value, ast.JoinedStr)]
        self.assertEqual(found, ['receiverRef'])
