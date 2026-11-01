"""P2 client gateway: authenticates to P1 and submits AES-GCM protected registration."""
from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pqcrypto.kem import ml_kem_768

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.qkd_simulation import bb84_simulated_key

P1_URL = os.getenv("P1_URL", "http://localhost:8001").rstrip("/")
P2_ID = os.getenv("P2_CLIENT_ID", "p2-demo-client")
QKD_SIMULATION_ENABLED = os.getenv("QKD_SIMULATION_ENABLED", "true").lower() in {"1", "true", "yes"}
QKD_SIMULATION_SEED_B64 = os.getenv("QKD_SIMULATION_SEED_B64")
if QKD_SIMULATION_ENABLED and not QKD_SIMULATION_SEED_B64:
    raise RuntimeError("QKD_SIMULATION_SEED_B64 is required when QKD_SIMULATION_ENABLED=true")
QKD_SIMULATION_SEED = base64.b64decode(QKD_SIMULATION_SEED_B64, validate=True) if QKD_SIMULATION_SEED_B64 else None
if QKD_SIMULATION_ENABLED and len(QKD_SIMULATION_SEED) < 32:
    raise RuntimeError("QKD_SIMULATION_SEED_B64 must decode to at least 32 bytes")
KEY_EXCHANGE_MODE = "ML-KEM-768+BB84-QISKIT-SIMULATED" if QKD_SIMULATION_ENABLED else "ML-KEM-768"
AAD_PREFIX = b"pricewatchin-bank-registration:v1:"


def b64d(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def kem_encaps(public_key: bytes) -> tuple[bytes, bytes]:
    """Support pqcrypto 1.x and the older 0.x function names."""
    return ml_kem_768.encaps(public_key) if hasattr(ml_kem_768, "encaps") else ml_kem_768.encrypt(public_key)


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
    return b"pricewatchin-handshake-v1\0" + KEY_EXCHANGE_MODE.encode() + b"\0" + handshake_id.encode() + b"\0" + client_id.encode() + b"\0" + kem_public_key


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=32)
    account_type: str = Field(min_length=1, max_length=32, examples=["savings"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "registration": {
                        "full_name": "Asha Rao",
                        "email": "asha@example.com",
                        "phone": "+919876543210",
                        "account_type": "savings",
                    }
                }
            ]
        },
    )
    registration: Registration


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=15)
    yield
    await app.state.http.aclose()


app = FastAPI(title="PriceWatchin P2 Client Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "p2-client-gateway", "client_id": P2_ID}


@app.get("/v1/qkd/status")
async def qkd_status():
    return {"enabled": QKD_SIMULATION_ENABLED, "mode": "qiskit-bb84-simulation" if QKD_SIMULATION_ENABLED else "disabled", "warning": "Simulation only; this is not physical QKD." if QKD_SIMULATION_ENABLED else None}


@app.get("/v1/identity")
async def identity():
    return {"client_id": P2_ID, "signature_algorithm": "Ed25519", "public_key_b64": base64.b64encode(CLIENT_PUBLIC_RAW).decode()}


@app.post("/v1/register", status_code=201)
async def register(request: RegisterRequest):
    http: httpx.AsyncClient = app.state.http
    try:
        init_response = await http.post(f"{P1_URL}/v1/handshakes")
        if not init_response.is_success:
            detail = init_response.text[:300]
            raise HTTPException(init_response.status_code, f"P1 POST /v1/handshakes failed: {detail}")
        hs = init_response.json()
        if hs.get("key_exchange_mode") != KEY_EXCHANGE_MODE:
            raise HTTPException(502, "P1/P2 key exchange modes differ; configure QKD simulation identically on both services")
        handshake_id = hs["handshake_id"]
        challenge = b64d(hs["challenge_b64"])
        kem_public_key = b64d(hs["kem_public_key_b64"])
        server_public = b64d(hs["server_signing_public_key_b64"])
        if PINNED_SERVER_KEY is None:
            raise HTTPException(
                503,
                "P1_ED25519_PUBLIC_KEY_B64 is missing from P2. Run scripts/setup_local_identities.py and restart both services with their generated env files.",
            )
        if not secrets.compare_digest(server_public, b64d(PINNED_SERVER_KEY)):
            raise HTTPException(502, "P1 identity did not match the pinned server key")
        server_signed = b"pricewatchin-server-handshake-v1\0" + KEY_EXCHANGE_MODE.encode() + b"\0" + handshake_id.encode() + b"\0" + challenge + b"\0" + kem_public_key
        Ed25519PublicKey.from_public_bytes(server_public).verify(b64d(hs["server_signature_b64"]), server_signed)

        ciphertext, shared_secret = kem_encaps(kem_public_key)
        client_signed = transcript(handshake_id, P2_ID, kem_public_key) + b"\0" + challenge
        signature = CLIENT_SIGNER.sign(client_signed)
        complete = await http.post(
            f"{P1_URL}/v1/handshakes/{handshake_id}/complete",
            json={"handshake_id": handshake_id, "client_id": P2_ID,
                  "client_signature_b64": base64.b64encode(signature).decode(),
                  "ciphertext_b64": base64.b64encode(ciphertext).decode()},
        )
        if not complete.is_success:
            detail = complete.text[:300]
            raise HTTPException(complete.status_code, f"P1 handshake completion failed: {detail}")
        session = complete.json()
        context = transcript(handshake_id, P2_ID, kem_public_key) + ciphertext
        input_key_material = shared_secret
        if QKD_SIMULATION_ENABLED:
            try:
                # The local Qiskit simulation is CPU-bound; do not block the
                # event loop while other registration requests are in flight.
                input_key_material += await asyncio.to_thread(bb84_simulated_key, QKD_SIMULATION_SEED, challenge)
            except Exception as exc:
                raise HTTPException(503, "Qiskit BB84 simulation could not establish a key") from exc
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=challenge, info=b"pricewatchin-registration-aes256gcm-v2\0" + context).derive(input_key_material)
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
            try:
                detail = result.json().get("detail", result.text[:300])
            except ValueError:
                detail = result.text[:300]
            raise HTTPException(result.status_code, f"P1 POST /v1/registrations failed: {detail}")
        return result.json()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not complete request with P1: {exc.__class__.__name__}") from exc
    except Exception as exc:
        raise HTTPException(502, "P1 handshake verification failed") from exc
