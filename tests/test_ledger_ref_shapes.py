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

        Calls `_literal_ref_assignments` against a temporary file rather than
        reimplementing the AST walk. A proof-of-life that shares no code with
        the assertion it backs only proves the COPY works -- it stays green
        while the real detector rots, which is the failure it exists to rule
        out.
        """
        found = self._scan("Transaction(receiverRef='platform', actorRole=x)")
        self.assertEqual(len(found), 1)
        self.assertIn("receiverRef='platform'", found[0])

    def test_the_check_catches_the_f_string_shape_too(self):
        found = self._scan('Transaction(receiverRef=f"users/{trip}")')
        self.assertEqual(len(found), 1)
        self.assertIn('receiverRef', found[0])

    def test_the_check_does_not_fire_on_a_proper_call(self):
        # Or it would be green for the wrong reason: a detector that flags
        # everything passes its own proof-of-life and fails the real file.
        self.assertEqual(self._scan('Transaction(receiverRef=user_ref_path(x))'), [])

    def _scan(self, source):
        """Run the real detector over `source`, via a file under app/."""
        tmp = APP / '_ledger_ref_shapes_probe.py'
        tmp.write_text(source)
        try:
            return [b for b in _literal_ref_assignments() if '_probe' in b]
        finally:
            tmp.unlink()
