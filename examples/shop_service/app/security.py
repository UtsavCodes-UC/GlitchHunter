from fastapi import Header, HTTPException

from .config import API_TOKEN


def require_token(authorization: str = Header(...)):
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")
    return "service-account"
