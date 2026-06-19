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


def _mint(uid: str, claims: dict | None = None) -> str:
    token = firebase_auth.create_custom_token(uid, claims) if claims else firebase_auth.create_custom_token(uid)
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def mint_impersonation_token(admin_uid: str, target_uid: str) -> dict:
    """Mint a view-only Firebase custom token for `target_uid`, plus a restore
    token so the admin can return to their own session on exit.

    `admin_uid` is asserted by the trusted Cloud Function; we still re-verify it
    is genuinely an admin here as defense-in-depth.
    """
    if not admin_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='admin_uid is required')
    if not target_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='target_uid is required')
    if target_uid == admin_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot impersonate yourself')

    admin_doc = db.collection('users').document(admin_uid).get()
    if not admin_doc.exists or not _is_admin(admin_doc.to_dict() or {}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Caller is not an admin')

    target_doc = db.collection('users').document(target_uid).get()
    if not target_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Target user not found')

    # Never let an admin impersonate another admin (privilege containment).
    if _is_admin(target_doc.to_dict() or {}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot impersonate another admin')

    # View-only session for the target; claims propagate into its ID token so
    # rules / payment endpoints can enforce view-only authoritatively.
    custom_token = _mint(target_uid, {'impersonated': True, 'imp_admin_uid': admin_uid, 'imp_view_only': VIEW_ONLY})
    # Clean admin session (no impersonation claims) used to exit without re-login.
    admin_restore_token = _mint(admin_uid)

    _write_audit(admin_uid, target_uid)

    app_logger.info('Admin %s minted impersonation token for user %s (view_only=%s)', admin_uid, target_uid, VIEW_ONLY)

    return {
        'custom_token': custom_token,
        'admin_restore_token': admin_restore_token,
        'target_uid': target_uid,
        'admin_uid': admin_uid,
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
