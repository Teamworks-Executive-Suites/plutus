from datetime import datetime, timezone

from fastapi import HTTPException
from firebase_admin import auth as firebase_auth
from starlette import status

from app.firebase_setup import db
from app.utils import app_logger

# Impersonation is VIEW-ONLY by product constraint: an admin must never be able to
# trigger a charge as the user. The claims below propagate into the impersonated
# session's ID token so Security Rules and payment endpoints can enforce this
# authoritatively (see design doc docs/design/admin-impersonation.md, Layer 2/3).
VIEW_ONLY = True
# Firebase custom tokens are valid for 1 hour; surfaced to the client for UX.
TOKEN_TTL_SECONDS = 3600


def _is_admin(user_data: dict) -> bool:
    return bool(user_data and user_data.get('isAdmin'))


def mint_impersonation_token(admin_uid: str, target_uid: str) -> dict:
    """Mint a Firebase custom token for `target_uid` on behalf of an admin.

    The caller has already been verified as an admin by the route dependency.
    """
    if not target_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='target_uid is required')

    if target_uid == admin_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot impersonate yourself')

    target_doc = db.collection('users').document(target_uid).get()
    if not target_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Target user not found')

    target_data = target_doc.to_dict() or {}

    # Never let an admin impersonate another admin (privilege containment).
    if _is_admin(target_data):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot impersonate another admin')

    developer_claims = {
        'impersonated': True,
        'imp_admin_uid': admin_uid,
        'imp_view_only': VIEW_ONLY,
    }

    custom_token = firebase_auth.create_custom_token(target_uid, developer_claims)
    if isinstance(custom_token, bytes):
        custom_token = custom_token.decode('utf-8')

    _write_audit(admin_uid, target_uid)

    app_logger.info('Admin %s minted impersonation token for user %s (view_only=%s)', admin_uid, target_uid, VIEW_ONLY)

    return {
        'custom_token': custom_token,
        'target_uid': target_uid,
        'view_only': VIEW_ONLY,
        'expires_in': TOKEN_TTL_SECONDS,
    }


def _write_audit(admin_uid: str, target_uid: str) -> None:
    """Best-effort audit record. A failure here must not block the admin, but is
    logged loudly so it can be alerted on."""
    record = {
        'admin_uid': admin_uid,
        'target_uid': target_uid,
        'view_only': VIEW_ONLY,
        'action': 'start',
        'created_at': datetime.now(timezone.utc),
    }
    try:
        db.collection('impersonation_audit').add(record)
    except Exception:  # noqa: BLE001 - audit must never break the request
        app_logger.exception('Failed to write impersonation audit record for admin %s -> %s', admin_uid, target_uid)
