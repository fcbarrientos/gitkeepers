"""Secure Sync & Transfer Protocol with Encrypted Key Envelope.

Packages local BHW/Midwife records into de-identified payloads safe for transit
over public internet, rural mesh, or USB transfers, with encrypted vault resolution for the RHU.
"""
import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core.pseudonymize import Pseudonymizer


def derive_key(secret: bytes | str, salt: bytes = b"gitkeepers-sync-salt") -> bytes:
    """Derive a 256-bit AES-GCM key from a shared secret passphrase or raw key."""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=b"gitkeepers-rhu-sync-key",
    )
    return hkdf.derive(secret)


def encrypt_vault(vault: dict[str, str], secret_key: bytes | str) -> dict[str, str]:
    """Encrypt identity lookup vault using AES-256-GCM."""
    key = derive_key(secret_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    data = json.dumps(vault, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }


def decrypt_vault(encrypted_vault: dict[str, str], secret_key: bytes | str) -> dict[str, str]:
    """Decrypt identity lookup vault with RHU/Hospital secret key."""
    key = derive_key(secret_key)
    aesgcm = AESGCM(key)
    nonce = base64.b64decode(encrypted_vault["nonce"])
    ciphertext = base64.b64decode(encrypted_vault["ciphertext"])
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(decrypted_bytes.decode("utf-8"))


def create_sync_bundle(records: list[dict[str, Any]], station_id: str,
                       secret_key: bytes | str, pseudonymizer: Pseudonymizer | None = None) -> dict[str, Any]:
    """Package clinical records into a secure, de-identified sync bundle."""
    pseudonymizer = pseudonymizer or Pseudonymizer(salt=f"rhu-sync-{station_id}")
    deidentified_records = [pseudonymizer.pseudonymize_record(r) for r in records]
    encrypted_vault = encrypt_vault(pseudonymizer.vault, secret_key)

    return {
        "format": "gitkeepers-sync-v1",
        "station_id": station_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "payload": deidentified_records,
        "identity_envelope": encrypted_vault,
    }


def unpack_and_resolve_bundle(bundle: dict[str, Any], secret_key: bytes | str) -> list[dict[str, Any]]:
    """Unpack sync bundle at RHU/Hospital and restore patient identities."""
    if bundle.get("format") != "gitkeepers-sync-v1":
        raise ValueError("Unsupported or invalid sync bundle format")

    vault = decrypt_vault(bundle["identity_envelope"], secret_key)
    pseudonymizer = Pseudonymizer()
    return [pseudonymizer.depseudonymize_record(r, vault=vault) for r in bundle["payload"]]


def unpack_deidentified_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Unpack bundle for statistical/epidemiological use without revealing patient identities."""
    if bundle.get("format") != "gitkeepers-sync-v1":
        raise ValueError("Unsupported or invalid sync bundle format")
    return bundle["payload"]
