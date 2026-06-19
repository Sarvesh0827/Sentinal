"""
Identity Registry: Agent KYA (Know Your Agent) module.

Manages per-tenant agent identities and their Ed25519 public keys.
Provides cryptographic signature verification for incoming events.
"""
import json
import hashlib
from typing import Dict, Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
    load_pem_public_key
)
from cryptography.exceptions import InvalidSignature
import base64

# Registry: tenant_id -> agent_id -> public_key_pem
_registry: Dict[str, Dict[str, Ed25519PublicKey]] = {}

# Trusted key registry (in production this would be backed by a DB/Redis)
_raw_public_keys: Dict[str, Dict[str, str]] = {}


def register_agent(tenant_id: str, agent_id: str, public_key_pem: str) -> None:
    """Register an agent's Ed25519 public key for signature verification."""
    if tenant_id not in _registry:
        _registry[tenant_id] = {}
        _raw_public_keys[tenant_id] = {}
    key = load_pem_public_key(public_key_pem.encode())
    _registry[tenant_id][agent_id] = key
    _raw_public_keys[tenant_id][agent_id] = public_key_pem


def get_public_key_pem(tenant_id: str, agent_id: str) -> Optional[str]:
    """Return the stored PEM public key, or None if not registered."""
    return _raw_public_keys.get(tenant_id, {}).get(agent_id)


def verify_event_signature(event: dict) -> bool:
    """
    Verify the Ed25519 signature on an incoming AgentAction event.
    
    Signature is computed over the canonical JSON of the event (without the
    'signature' field itself), and stored base64-encoded in event['signature'].
    
    Returns True if signature is valid, or if no key is registered (permissive mode).
    Returns False only if a key IS registered and the signature is invalid.
    """
    tenant_id = event.get("tenant_id", "default")
    agent_id = event.get("agent_id", "")
    signature_b64 = event.get("signature")

    if tenant_id not in _registry or agent_id not in _registry[tenant_id]:
        # No key registered — permissive, allow through (useful for dev/warmup)
        return True

    if not signature_b64:
        # Key registered but no signature provided — reject
        return False

    pub_key = _registry[tenant_id][agent_id]

    # Canonical payload excludes the signature field itself
    payload = {k: v for k, v in event.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    try:
        sig_bytes = base64.b64decode(signature_b64)
        pub_key.verify(sig_bytes, canonical.encode())
        return True
    except (InvalidSignature, Exception):
        return False


def generate_agent_keypair() -> tuple[str, str]:
    """
    Utility: generate a fresh Ed25519 keypair for testing/demo.
    Returns (private_key_pem, public_key_pem).
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    return private_pem, public_pem


def sign_event(event: dict, private_key_pem: str) -> str:
    """
    Utility: sign a canonical event payload with an Ed25519 private key.
    Returns a base64-encoded signature string to set as event['signature'].
    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    private_key = load_pem_private_key(private_key_pem.encode(), password=None)
    payload = {k: v for k, v in event.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig_bytes = private_key.sign(canonical.encode())
    return base64.b64encode(sig_bytes).decode()
