"""
Simple static bearer-token authentication for the internal trading API.

Single-user internal tool: one long random API_ACCESS_TOKEN lives in
backend/.env. Every request to a protected route must send:

    Authorization: Bearer <API_ACCESS_TOKEN>

This dependency is attached to the whole `/api` router in server.py, so it
protects every route (orders, settings, auto-trader controls, etc.) without
needing to repeat Depends() on each endpoint.
"""
import os
import secrets
from fastapi import Header, HTTPException, status


def verify_token(authorization: str = Header(None)):
    expected_token = os.environ.get('API_ACCESS_TOKEN')

    if not expected_token:
        # Server misconfigured - fail closed, never allow open access
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: API_ACCESS_TOKEN not set"
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = parts[1]
    if not secrets.compare_digest(token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API access token",
            headers={"WWW-Authenticate": "Bearer"}
        )
