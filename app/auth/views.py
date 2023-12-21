from fastapi import APIRouter, Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from app.auth.tasks import generate_bearer_token
from app.main import settings
from app.models import UnauthorizedMessage
import typing as t

auth_router = APIRouter()

# Auth
generate_bearer_token()
# gets the bearer token from the file for verification
known_tokens = set()
with open("bearer_token.txt", "r") as import_file:
    btoken = import_file.read().strip()
known_tokens.add(btoken)

# We will handle a missing token ourselves
get_bearer_token = HTTPBearer(auto_error=False)

async def get_token(
        auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # If settings.testing is True, return a dummy token
    debug(settings.testing)
    if settings.test_token:
        known_tokens.add(settings.test_token)

    # Simulate a database query to find a known token
    debug(known_tokens)
    if auth is None or (token := auth.credentials) not in known_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UnauthorizedMessage().detail,
            # Assuming UnauthorizedMessage is defined somewhere in your actual code
        )
    return token