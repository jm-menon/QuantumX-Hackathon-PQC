"""P2 client gateway: authenticates to P1 and submits AES-GCM protected registration."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pqcrypto.kem import ml_kem_768

P1_URL = os.getenv("P1_URL", "http://localhost:8000").rstrip("/")
P2_ID = os.getenv("P2_CLIENT_ID", "p2-demo-client")
AAD_PREFIX = b"pricewatchin-bank-registration:v1:"


def b64d(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def load_client_signer() -> Ed25519PrivateKey:
    seed = os.getenv("P2_ED25519_PRIVATE_KEY_B64")
    if seed:
        raw = b64d(seed)
        if len(raw) != 32:
            raise RuntimeError("P2_ED25519_PRIVATE_KEY_B64 must encode a 32-byte Ed25519 seed")
        return Ed25519PrivateKey.from_private_bytes(raw)
    # Development-only convenience. Pin the matching public key in P1 TRUSTED_CLIENTS_JSON.
    return Ed25519PrivateKey.generate()


CLIENT_SIGNER = load_client_signer()
CLIENT_PUBLIC_RAW = CLIENT_SIGNER.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
PINNED_SERVER_KEY = os.getenv("P1_ED25519_PUBLIC_KEY_B64")


def transcript(handshake_id: str, client_id: str, kem_public_key: bytes) -> bytes:
    return b"pricewatchin-handshake-v1\0" + handshake_id.encode() + b"\0" + client_id.encode() + b"\0" + kem_public_key


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=32)
    account_type: str = Field(min_length=1, max_length=32, examples=["savings"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration: Registration


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=15)
    yield
    await app.state.http.aclose()


app = FastAPI(title="PriceWatchin P2 Client Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "p2-client-gateway", "client_id": P2_ID}


@app.get("/v1/identity")
async def identity():
    return {"client_id": P2_ID, "signature_algorithm": "Ed25519", "public_key_b64": base64.b64encode(CLIENT_PUBLIC_RAW).decode()}


@app.post("/v1/register", status_code=201)
async def register(request: RegisterRequest):
    http: httpx.AsyncClient = app.state.http
    try:
        init_response = await http.post(f"{P1_URL}/v1/handshakes")
        init_response.raise_for_status()
        hs = init_response.json()
        handshake_id = hs["handshake_id"]
        challenge = b64d(hs["challenge_b64"])
        kem_public_key = b64d(hs["kem_public_key_b64"])
        server_public = b64d(hs["server_signing_public_key_b64"])
        if PINNED_SERVER_KEY is None:
            raise HTTPException(503, "P1_ED25519_PUBLIC_KEY_B64 must pin the P1 signing key")
        if not secrets.compare_digest(server_public, b64d(PINNED_SERVER_KEY)):
            raise HTTPException(502, "P1 identity did not match the pinned server key")
        server_signed = b"pricewatchin-server-handshake-v1\0" + handshake_id.encode() + b"\0" + challenge + b"\0" + kem_public_key
        Ed25519PublicKey.from_public_bytes(server_public).verify(b64d(hs["server_signature_b64"]), server_signed)

        ciphertext, shared_secret = ml_kem_768.encrypt(kem_public_key)
        client_signed = transcript(handshake_id, P2_ID, kem_public_key) + b"\0" + challenge
        signature = CLIENT_SIGNER.sign(client_signed)
        complete = await http.post(
            f"{P1_URL}/v1/handshakes/{handshake_id}/complete",
            json={"handshake_id": handshake_id, "client_id": P2_ID,
                  "client_signature_b64": base64.b64encode(signature).decode(),
                  "ciphertext_b64": base64.b64encode(ciphertext).decode()},
        )
        complete.raise_for_status()
        session = complete.json()
        context = transcript(handshake_id, P2_ID, kem_public_key) + ciphertext
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=challenge, info=b"pricewatchin-registration-aes256gcm-v1\0" + context).derive(shared_secret)
        proof = hashlib.sha256(b"pricewatchin-server-finished-v1\0" + context + key).digest()
        if not secrets.compare_digest(proof, b64d(session["server_proof_b64"])):
            raise HTTPException(502, "P1 key confirmation failed")
        finished_sig = b"pricewatchin-server-finished-v1\0" + session["session_id"].encode() + b"\0" + proof
        Ed25519PublicKey.from_public_bytes(server_public).verify(b64d(session["server_signature_b64"]), finished_sig)

        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(request.registration.model_dump(mode="json"), separators=(",", ":")).encode()
        encrypted = AESGCM(key).encrypt(nonce, plaintext, AAD_PREFIX + session["session_id"].encode())
        result = await http.post(
            f"{P1_URL}/v1/registrations",
            headers={"X-Session-ID": session["session_id"]},
            json={"nonce_b64": base64.b64encode(nonce).decode(), "ciphertext_b64": base64.b64encode(encrypted).decode()},
        )
        if result.status_code >= 400:
            raise HTTPException(result.status_code, result.json().get("detail", "P1 rejected registration"))
        return result.json()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not complete request with P1: {exc.__class__.__name__}") from exc
    except Exception as exc:
        raise HTTPException(502, "P1 handshake verification failed") from exc
