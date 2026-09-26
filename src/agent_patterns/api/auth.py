"""Reviewer authentication and server-assigned tenant identity."""

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def reviewer_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
) -> tuple[str, str]:
    """Return the reviewer and tenant bound to the configured bearer secret."""

    settings = request.app.state.settings
    if (
        settings.reviewer_api_key is None
        or not settings.reviewer_api_key.get_secret_value()
    ):
        raise HTTPException(status_code=503, detail="Reviewer authentication is not configured")
    if credentials is None or not compare_digest(
        credentials.credentials, settings.reviewer_api_key.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid reviewer bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return settings.reviewer_id, settings.tenant_id
