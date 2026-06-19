from fastapi import APIRouter, Depends

from app.admin.tasks import mint_impersonation_token
from app.auth.views import get_token
from app.models import ImpersonationTokenRequest, ImpersonationTokenResponse
from app.utils import app_logger

admin_router = APIRouter()


@admin_router.post('/admin/impersonation_token', response_model=ImpersonationTokenResponse)
def impersonation_token(
    data: ImpersonationTokenRequest,
    token: str = Depends(get_token),
):
    """Mint a view-only impersonation token for an admin.

    Transport model (Option A): this endpoint is only reachable by the trusted
    Cloud Function proxy, which authenticates with the static ``master_token``
    (``get_token``) and asserts the caller's Firebase-verified ``admin_uid`` in
    the body. Plutus re-checks that ``admin_uid`` is genuinely an admin as
    defense-in-depth before minting (see ``mint_impersonation_token``).
    """
    app_logger.info('Impersonation token requested: admin %s -> target %s', data.admin_uid, data.target_uid)
    return mint_impersonation_token(data.admin_uid, data.target_uid)
