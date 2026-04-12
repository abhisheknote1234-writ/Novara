"""
security.py — Encryption, Consent, and Anonymization
======================================================
Fernet symmetric encryption for PII fields.
Consent gating before any data sharing.
Patient anonymization for exports.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

from novara.config import KEY_PATH, ACCESS_TOKEN_EXPIRY_HOURS


class SecurityManager:
    """
    Handles all security operations:
    - Fernet key management
    - Encrypt / decrypt sensitive strings
    - Consent verification
    - Patient data anonymization
    - Time-limited access tokens
    """

    def __init__(self):
        self._fernet = None
        self._tokens = {}  # token → {patient_id, doctor_id, expires_at}
        self._load_or_create_key()

    # ─── Key Management ──────────────────────────────────────────

    def _load_or_create_key(self):
        """Load existing Fernet key or generate a new one."""
        if os.path.exists(KEY_PATH):
            with open(KEY_PATH, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
            with open(KEY_PATH, "wb") as f:
                f.write(key)
        self._fernet = Fernet(key)

    # ─── Encryption ──────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a plaintext string → Fernet ciphertext bytes."""
        if not plaintext:
            return self._fernet.encrypt(b"")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt Fernet ciphertext bytes → plaintext string."""
        if not ciphertext:
            return ""
        return self._fernet.decrypt(ciphertext).decode("utf-8")

    # ─── Consent ─────────────────────────────────────────────────

    def check_consent(self, patient) -> bool:
        """Check if patient has given consent for data sharing."""
        return bool(patient.consent_given)

    def require_consent(self, patient) -> None:
        """Raise if consent not granted."""
        if not self.check_consent(patient):
            raise PermissionError(
                f"Patient {patient.patient_id} has not given consent for data sharing. "
                "Obtain explicit consent before proceeding."
            )

    # ─── Anonymization ───────────────────────────────────────────

    def anonymize_patient(self, patient_dict: dict) -> dict:
        """
        Strip PII from patient data for anonymous exports.
        Returns a copy with identifiers replaced by hashes.
        """
        anon = dict(patient_dict)

        # Replace identifiable fields
        if "name" in anon:
            anon["name"] = "ANONYMIZED"
        if "patient_id" in anon:
            # Deterministic hash so the same patient gets the same anon ID
            h = hashlib.sha256(anon["patient_id"].encode()).hexdigest()[:12]
            anon["patient_id"] = f"ANON-{h.upper()}"
        if "medical_notes" in anon:
            anon["medical_notes"] = "[REDACTED]"
        if "blood_type" in anon:
            anon["blood_type"] = "[REDACTED]"

        return anon

    # ─── Access Tokens ───────────────────────────────────────────

    def generate_access_token(self, patient_id: str, doctor_id: str) -> str:
        """
        Generate a short-lived access token for doctor access.
        Token expires after ACCESS_TOKEN_EXPIRY_HOURS.
        """
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {
            "patient_id": patient_id,
            "doctor_id":  doctor_id,
            "expires_at": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRY_HOURS),
            "created_at": datetime.utcnow(),
        }
        return token

    def validate_access(self, token: str) -> dict:
        """
        Validate an access token.
        Returns the token metadata if valid, raises otherwise.
        """
        if token not in self._tokens:
            raise PermissionError("Invalid access token.")

        meta = self._tokens[token]
        if datetime.utcnow() > meta["expires_at"]:
            del self._tokens[token]
            raise PermissionError("Access token has expired.")

        return meta

    def revoke_token(self, token: str) -> None:
        """Revoke an access token."""
        self._tokens.pop(token, None)


# ─── Module-level singleton ──────────────────────────────────────
_security_mgr = None

def get_security_manager() -> SecurityManager:
    """Get or create the singleton SecurityManager."""
    global _security_mgr
    if _security_mgr is None:
        _security_mgr = SecurityManager()
    return _security_mgr
