import os

# Must be set before app.settings / app.firebase_setup load so `db` binds to the
# in-memory MockFirestore rather than a real Firestore client.
os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402
from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.firebase_setup import MOCK_DB  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

ADMIN_UID = 'admin_uid'
TARGET_UID = 'target_uid'
OTHER_ADMIN_UID = 'other_admin_uid'
NON_ADMIN_UID = 'non_admin_uid'

CREATE = 'app.admin.tasks.firebase_auth.create_custom_token'


class TestImpersonationToken(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.collection('users').document(ADMIN_UID).set({'isAdmin': True})
        self.db.collection('users').document(OTHER_ADMIN_UID).set({'isAdmin': True})
        self.db.collection('users').document(NON_ADMIN_UID).set({'isAdmin': False})
        self.db.collection('users').document(TARGET_UID).set({'isAdmin': False, 'display_name': 'Debra'})
        # Option A: the trusted Cloud Function authenticates with the master/test token.
        self.headers = {'Authorization': f'Bearer {settings.test_token}'}

    def _post(self, admin_uid, target_uid, headers=None):
        return client.post(
            '/admin/impersonation_token',
            headers=self.headers if headers is None else headers,
            json={'admin_uid': admin_uid, 'target_uid': target_uid},
        )

    @patch(CREATE, return_value=b'tok')
    def test_admin_can_mint_tokens(self, _create):
        r = self._post(ADMIN_UID, TARGET_UID)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['custom_token'], 'tok')
        self.assertEqual(body['admin_restore_token'], 'tok')
        self.assertEqual(body['target_uid'], TARGET_UID)
        self.assertEqual(body['admin_uid'], ADMIN_UID)
        self.assertTrue(body['view_only'])
        # Two tokens minted: target (view-only claims) + admin restore (clean).
        self.assertEqual(_create.call_count, 2)
        target_call = next(c for c in _create.call_args_list if c.args[0] == TARGET_UID)
        self.assertEqual(target_call.args[1], {'impersonated': True, 'imp_admin_uid': ADMIN_UID, 'imp_view_only': True})
        restore_call = next(c for c in _create.call_args_list if c.args[0] == ADMIN_UID)
        # restore token carries no impersonation claims
        self.assertEqual(len(restore_call.args), 1)

    @patch(CREATE, return_value=b'tok')
    def test_asserted_admin_must_actually_be_admin(self, _create):
        r = self._post(NON_ADMIN_UID, TARGET_UID)
        self.assertEqual(r.status_code, 403, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'tok')
    def test_cannot_impersonate_admin(self, _create):
        r = self._post(ADMIN_UID, OTHER_ADMIN_UID)
        self.assertEqual(r.status_code, 403, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'tok')
    def test_cannot_impersonate_self(self, _create):
        r = self._post(ADMIN_UID, ADMIN_UID)
        self.assertEqual(r.status_code, 400, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'tok')
    def test_target_not_found(self, _create):
        r = self._post(ADMIN_UID, 'does_not_exist')
        self.assertEqual(r.status_code, 404, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'tok')
    def test_missing_master_token_unauthorized(self, _create):
        r = self._post(ADMIN_UID, TARGET_UID, headers={})
        self.assertEqual(r.status_code, 401, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'tok')
    def test_wrong_master_token_unauthorized(self, _create):
        r = self._post(ADMIN_UID, TARGET_UID, headers={'Authorization': 'Bearer nope'})
        self.assertEqual(r.status_code, 401, r.text)
        _create.assert_not_called()
