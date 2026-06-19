"""Tests for KYA identity module: Ed25519 key registration and signature verification."""
import pytest
from src.identity import (
    register_agent,
    verify_event_signature,
    generate_agent_keypair,
    sign_event,
)

TENANT = "test-tenant"
AGENT = "agent-kya-001"


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the identity registry between tests."""
    from src.identity import _registry, _raw_public_keys
    _registry.clear()
    _raw_public_keys.clear()
    yield
    _registry.clear()
    _raw_public_keys.clear()


def make_event(agent_id=AGENT, tenant_id=TENANT, signature=None):
    return {
        "event_id": "test-event-1",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "action_type": "purchase",
        "merchant": "merchant-1",
        "amount": 42.0,
        "currency": "USD",
        "timestamp": "2026-06-22T00:00:00+00:00",
        "trace_id": "trace-1",
        "signature": signature,
    }


def test_no_key_registered_permissive():
    """Events from agents with no registered key should be allowed through."""
    event = make_event()
    assert verify_event_signature(event) is True


def test_valid_signature_accepted():
    """A correctly signed event should pass verification."""
    priv_pem, pub_pem = generate_agent_keypair()
    register_agent(TENANT, AGENT, pub_pem)

    event = make_event()
    sig = sign_event(event, priv_pem)
    event["signature"] = sig

    assert verify_event_signature(event) is True


def test_missing_signature_rejected_when_key_registered():
    """If a key is registered but no signature is provided, reject the event."""
    _, pub_pem = generate_agent_keypair()
    register_agent(TENANT, AGENT, pub_pem)

    event = make_event(signature=None)
    assert verify_event_signature(event) is False


def test_tampered_event_rejected():
    """Changing the event payload after signing should invalidate the signature."""
    priv_pem, pub_pem = generate_agent_keypair()
    register_agent(TENANT, AGENT, pub_pem)

    event = make_event()
    event["signature"] = sign_event(event, priv_pem)

    # Tamper with the amount after signing
    event["amount"] = 99999.99
    assert verify_event_signature(event) is False


def test_wrong_key_rejected():
    """A signature from a different key should fail."""
    _, pub_pem = generate_agent_keypair()  # Register key A
    register_agent(TENANT, AGENT, pub_pem)

    other_priv, _ = generate_agent_keypair()  # Sign with key B
    event = make_event()
    event["signature"] = sign_event(event, other_priv)

    assert verify_event_signature(event) is False


def test_cross_tenant_isolation():
    """A key registered for tenant A should NOT validate events from tenant B."""
    priv_pem, pub_pem = generate_agent_keypair()
    register_agent("tenant-A", AGENT, pub_pem)

    event = make_event(tenant_id="tenant-B")  # Different tenant
    event["signature"] = sign_event(event, priv_pem)

    # No key registered for tenant-B → permissive mode → True
    assert verify_event_signature(event) is True

    # Register a DIFFERENT key for tenant-B
    _, other_pub = generate_agent_keypair()
    register_agent("tenant-B", AGENT, other_pub)

    # Now the signature (from tenant-A's key) should be rejected for tenant-B
    assert verify_event_signature(event) is False
