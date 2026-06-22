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
    try:
        # Check if Neon Auth is configured
        if settings.NEON_AUTH_BASE_URL:
            jwks = await get_neon_jwks()
            if jwks:
                # Get the unverified header to extract the kid
                unverified_header = jwt.get_unverified_header(token)
                rsa_key = {}
                for key in jwks.get("keys", []):
                    if key["kid"] == unverified_header.get("kid"):
                        rsa_key = key
                        break
                if rsa_key:
                    payload = jwt.decode(
                        token,
                        rsa_key,
                        algorithms=["RS256"],
                        audience=None,
                        issuer=settings.NEON_AUTH_BASE_URL
                    )
                    return payload.get("sub")
            # Neon Auth is configured but token didn't match any key — reject it.
            # Do NOT fall back to local JWT to prevent forged HS256 tokens from bypassing Neon Auth.
            return None
        
        # Local JWT — only used when Neon Auth is NOT configured
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
