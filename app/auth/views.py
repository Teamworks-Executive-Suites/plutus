import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from app.utils import settings

from app.models import UnauthorizedMessage
import typing as t

auth_router = APIRouter()

# Auth
known_tokens = set()

# We will handle a missing token ourselves
get_bearer_token = HTTPBearer(auto_error=False)


async def get_token(
        auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # If settings.testing is True, return a dummy token
    if settings.testing:
        known_tokens.add(settings.test_token)

    if settings.master_token:
        known_tokens.add(settings.master_token)

    debug(known_tokens)

    # Simulate a database query to find a known token
    if auth is None or (token := auth.credentials) not in known_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UnauthorizedMessage().detail,
            # Assuming UnauthorizedMessage is defined somewhere in your actual code
        )
    return token
