"""Symmetric encryption for the Microsoft refresh token blob.

The refresh token rotates on nearly every use, and this repo is public, so
the token is never committed in plaintext. It's encrypted with a passphrase
that lives only as the SYNC_SECRET_KEY secret in the routine's environment.
"""
import base64
import hashlib

from cryptography.fernet import Fernet


def _key_from_passphrase(passphrase: str) -> bytes:
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str, passphrase: str) -> bytes:
    return Fernet(_key_from_passphrase(passphrase)).encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes, passphrase: str) -> str:
    return Fernet(_key_from_passphrase(passphrase)).decrypt(token).decode("utf-8")
