"""
JWT Authentication for Sentinel API.

Provides:
  - JWT creation (for login/token endpoints)
  - JWT validation via FastAPI dependency injection
  - API key validation (for programmatic /act access)

All tokens encode a 'tenant_id' claim so every endpoint knows
which tenant's data to read/write.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

try:
    from jose import JWTError, jwt
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration (loaded from env; sane defaults for dev)
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "sentinel-dev-secret-do-not-use-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Static API keys for programmatic /act access — map key → tenant_id
# In production, store hashed keys in Redis / DB.
_API_KEYS: dict[str, str] = {
    "sentinel-dev-key-0001": "default",
}

# ---------------------------------------------------------------------------
# Schemes
# ---------------------------------------------------------------------------
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------
def create_access_token(tenant_id: str, sub: str, expires_delta: Optional[timedelta] = None) -> str:
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose is not installed. Run: pip install python-jose[cryptography]")
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": sub, "tenant_id": tenant_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Dependency: resolve caller identity (tenant_id, subject)
# ---------------------------------------------------------------------------
class CallerIdentity:
    def __init__(self, tenant_id: str, sub: str):
        self.tenant_id = tenant_id
        self.sub = sub


def _resolve_from_bearer(credentials: HTTPAuthorizationCredentials) -> Optional[CallerIdentity]:
    if not _JOSE_AVAILABLE:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        tenant_id: str = payload.get("tenant_id", "default")
        sub: str = payload.get("sub", "unknown")
        return CallerIdentity(tenant_id=tenant_id, sub=sub)
    except JWTError:
        return None


def _resolve_from_api_key(api_key: str) -> Optional[CallerIdentity]:
    tenant_id = _API_KEYS.get(api_key)
    if tenant_id:
        return CallerIdentity(tenant_id=tenant_id, sub=f"apikey:{api_key[:8]}...")
    return None


async def get_caller(
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
) -> CallerIdentity:
    """
    FastAPI dependency. Resolves tenant identity from:
      1. Bearer JWT token (dashboard / interactive users)
      2. X-API-Key header (programmatic / generator access)
      3. Falls back to 'default' tenant in dev mode (no key required)
    """
    if bearer:
        identity = _resolve_from_bearer(bearer)
        if identity:
            return identity

    if api_key:
        identity = _resolve_from_api_key(api_key)
        if identity:
            return identity

    # Dev fallback: no auth required → use default tenant
    dev_mode = os.getenv("AUTH_REQUIRED", "false").lower() != "true"
    if dev_mode:
        return CallerIdentity(tenant_id="default", sub="anonymous-dev")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Provide a Bearer token or X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )
