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

VERIFY = 'app.admin.views.firebase_auth.verify_id_token'
CREATE = 'app.admin.tasks.firebase_auth.create_custom_token'


class TestImpersonationToken(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.collection('users').document(ADMIN_UID).set({'isAdmin': True})
        self.db.collection('users').document(OTHER_ADMIN_UID).set({'isAdmin': True})
        self.db.collection('users').document(TARGET_UID).set({'isAdmin': False, 'display_name': 'Debra'})
        self.headers = {'Authorization': 'Bearer fake-id-token'}

    def _post(self, target_uid):
        return client.post('/admin/impersonation_token', headers=self.headers, json={'target_uid': target_uid})

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': ADMIN_UID})
    def test_admin_can_mint_token(self, _verify, _create):
        r = self._post(TARGET_UID)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['custom_token'], 'fake-custom-token')
        self.assertEqual(body['target_uid'], TARGET_UID)
        self.assertTrue(body['view_only'])
        # claims must mark the session as impersonated + view-only
        _create.assert_called_once()
        args, _ = _create.call_args
        self.assertEqual(args[0], TARGET_UID)
        self.assertEqual(args[1], {'impersonated': True, 'imp_admin_uid': ADMIN_UID, 'imp_view_only': True})

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': TARGET_UID})
    def test_non_admin_forbidden(self, _verify, _create):
        r = self._post(ADMIN_UID)
        self.assertEqual(r.status_code, 403, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': ADMIN_UID})
    def test_cannot_impersonate_admin(self, _verify, _create):
        r = self._post(OTHER_ADMIN_UID)
        self.assertEqual(r.status_code, 403, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': ADMIN_UID})
    def test_cannot_impersonate_self(self, _verify, _create):
        r = self._post(ADMIN_UID)
        self.assertEqual(r.status_code, 400, r.text)
        _create.assert_not_called()

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': ADMIN_UID})
    def test_target_not_found(self, _verify, _create):
        r = self._post('does_not_exist')
        self.assertEqual(r.status_code, 404, r.text)
        _create.assert_not_called()

    @patch(VERIFY, side_effect=ValueError('bad token'))
    def test_invalid_token_unauthorized(self, _verify):
        r = self._post(TARGET_UID)
        self.assertEqual(r.status_code, 401, r.text)

    def test_missing_token_unauthorized(self):
        r = client.post('/admin/impersonation_token', json={'target_uid': TARGET_UID})
        self.assertEqual(r.status_code, 401, r.text)

    @patch(CREATE, return_value=b'fake-custom-token')
    @patch(VERIFY, return_value={'uid': ADMIN_UID, 'admin': True})
    def test_custom_claim_admin_allowed(self, _verify, _create):
        # An admin identified purely via custom claim (no Firestore isAdmin) is allowed.
        self.db.collection('users').document('claim_only_admin').set({'isAdmin': False})
        r = self._post(TARGET_UID)
        self.assertEqual(r.status_code, 200, r.text)
