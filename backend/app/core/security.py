from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
from jose import JWTError, jwt
import bcrypt
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

import json
import httpx
from cachetools import TTLCache
import asyncio

# Cache JWKS for 15 minutes to prevent DoS and handle key rotation
jwks_cache = TTLCache(maxsize=1, ttl=900)

async def get_neon_jwks():
    if not settings.NEON_AUTH_BASE_URL:
        return None
        
    # Check cache first
    if "jwks" in jwks_cache:
        return jwks_cache["jwks"]
        
    try:
        jwks_url = f"{settings.NEON_AUTH_BASE_URL}/.well-known/jwks.json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks_data = response.json()
            jwks_cache["jwks"] = jwks_data
            return jwks_data
    except Exception as e:
        print(f"Failed to fetch Neon JWKS: {e}")
        return None

async def decode_token(token: str) -> Optional[str]:
    """
    Verify a bearer token and return its subject, or None.

    Routing is decided by the token's own `alg` header, and each branch is
    verified against only its own key material:
      * RS256 -> Neon Auth, verified against the fetched JWKS.
      * HS256 -> issued by this service, verified against SECRET_KEY.

    Keying each algorithm separately is what rules out an algorithm-confusion
    attack: a JWKS public key is never accepted as an HMAC secret, so an
    attacker cannot re-sign an RS256 token as HS256 and have it validate.
    """
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except JWTError:
        return None

    # --- Locally issued token (this is what /auth/login and /auth/google mint) ---
    if alg == settings.ALGORITHM:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            return payload.get("sub")
        except JWTError:
            return None

    # --- Neon Auth token ---
    if alg == "RS256" and settings.NEON_AUTH_BASE_URL:
        jwks = await get_neon_jwks()
        if not jwks:
            return None
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            rsa_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
            if not rsa_key:
                return None
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=None,
                issuer=settings.NEON_AUTH_BASE_URL
            )
            return payload.get("sub")
        except JWTError:
            return None

    return None
