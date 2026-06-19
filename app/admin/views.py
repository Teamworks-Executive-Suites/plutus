import typing as t

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from starlette import status

from app.admin.tasks import mint_impersonation_token
from app.firebase_setup import db
from app.models import ImpersonationTokenRequest, ImpersonationTokenResponse
from app.utils import app_logger

admin_router = APIRouter()

# Unlike the rest of Plutus (which authenticates the *app* with a static
# master_token), admin endpoints must authenticate a *user* and confirm they are
# an admin. We therefore verify the caller's Firebase ID token directly.
get_bearer_token = HTTPBearer(auto_error=False)


def get_admin_uid(
    auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    """Verify the bearer is a valid Firebase ID token for an admin user.

    Returns the admin's uid. Raises 401 for missing/invalid tokens and 403 when
    the authenticated user is not an admin.
    """
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing authorization')

    try:
        decoded = firebase_auth.verify_id_token(auth.credentials)
    except Exception:  # noqa: BLE001 - any verification failure is a 401
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired ID token')

    uid = decoded.get('uid')
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token missing uid')

    # Authoritative gate. Prefer a tamper-proof custom claim (`admin: true`); fall
    # back to the users/<uid>.isAdmin Firestore flag so this works before claims
    # are backfilled. The Firestore flag MUST be write-locked to the Admin SDK.
    if decoded.get('admin') is True:
        return uid

    user_doc = db.collection('users').document(uid).get()
    if not user_doc.exists or not (user_doc.to_dict() or {}).get('isAdmin'):
        app_logger.warning('Non-admin user %s attempted to use an admin endpoint', uid)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Caller is not an admin')

    return uid


@admin_router.post('/admin/impersonation_token', response_model=ImpersonationTokenResponse)
def impersonation_token(
    data: ImpersonationTokenRequest,
    admin_uid: str = Depends(get_admin_uid),
):
    app_logger.info('Admin %s requested an impersonation token for %s', admin_uid, data.target_uid)
    return mint_impersonation_token(admin_uid, data.target_uid)
