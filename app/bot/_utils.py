"""Auth for the bot data endpoints.

A token of its own rather than the master token. The caller is a public-facing
marketing site, and the master token can issue refunds and off-session payments —
if it leaks there, the blast radius should be "read property availability", not
"move money".
"""

import typing as t

from fastapi import Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from app.utils import settings

get_bearer_token = HTTPBearer(auto_error=False)


async def get_bot_token(
    auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    accepted = {t for t in (settings.bot_token, settings.test_token if settings.testing else '') if t}

    if not accepted:
        # Refuse rather than fall open: an unset bot_token in production would
        # otherwise publish the whole property catalogue.
        raise HTTPException(status_code=503, detail='Bot endpoints are not configured.')

    if auth is None or auth.credentials not in accepted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')

    return auth.credentials
