"""P1: authenticated ML-KEM key establishment and encrypted bank registration API."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pqcrypto.kem import ml_kem_768

P1_ID = os.getenv("P1_ID", "p1-bank-api")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "600"))
BANK_ADMIN_TOKEN = os.getenv("BANK_ADMIN_TOKEN")
HANDSHAKE_TTL = 120
AAD_PREFIX = b"pricewatchin-bank-registration:v1:"


def b64d(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64") from exc


def load_server_signer() -> Ed25519PrivateKey:
    seed = os.getenv("P1_ED25519_PRIVATE_KEY_B64")
    if not seed:
        # Convenient for local demos. Production must provide a persistent key.
        return Ed25519PrivateKey.generate()
    raw = b64d(seed)
    if len(raw) != 32:
        raise RuntimeError("P1_ED25519_PRIVATE_KEY_B64 must encode a 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(raw)


SERVER_SIGNER = load_server_signer()
SERVER_PUBLIC_RAW = SERVER_SIGNER.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)


def configured_clients() -> dict[str, bytes]:
    raw = os.getenv("TRUSTED_CLIENTS_JSON", "{}")
    try:
        parsed = json.loads(raw)
        return {str(client_id): b64d(public_key) for client_id, public_key in parsed.items()}
    except Exception as exc:
        raise RuntimeError("TRUSTED_CLIENTS_JSON must map client IDs to base64 Ed25519 public keys") from exc


TRUSTED_CLIENTS = configured_clients()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        await app.state.redis.ping()
    except RedisError as exc:
        await app.state.redis.aclose()
        raise RuntimeError(f"Redis is unavailable at {REDIS_URL}") from exc
    yield
    await app.state.redis.aclose()


app = FastAPI(title="PriceWatchin P1 Bank API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-ID"],
)


class HandshakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handshake_id: str = Field(min_length=32, max_length=64)
    client_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    client_signature_b64: str
    ciphertext_b64: str


class EncryptedRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nonce_b64: str
    ciphertext_b64: str


def transcript(handshake_id: str, client_id: str, kem_public_key: bytes) -> bytes:
    return b"pricewatchin-handshake-v1\0" + handshake_id.encode() + b"\0" + client_id.encode() + b"\0" + kem_public_key


@app.get("/health")
async def health():
    return {"status": "ok", "service": P1_ID}


@app.get("/v1/identity")
async def identity():
    """Out-of-band pin this Ed25519 key in P2; TLS is still required in deployment."""
    return {"server_id": P1_ID, "signature_algorithm": "Ed25519", "public_key_b64": base64.b64encode(SERVER_PUBLIC_RAW).decode()}


@app.post("/v1/handshakes", status_code=201)
async def start_handshake():
    redis: Redis = app.state.redis
    public_key, secret_key = ml_kem_768.keygen()
    handshake_id = secrets.token_urlsafe(24)
    challenge = secrets.token_bytes(32)
    await redis.setex(
        f"pw:handshake:{handshake_id}", HANDSHAKE_TTL,
        json.dumps({"secret_key": base64.b64encode(secret_key).decode(), "challenge": base64.b64encode(challenge).decode(), "public_key": base64.b64encode(public_key).decode()}),
    )
    signed = b"pricewatchin-server-handshake-v1\0" + handshake_id.encode() + b"\0" + challenge + b"\0" + public_key
    return {
        "handshake_id": handshake_id,
        "challenge_b64": base64.b64encode(challenge).decode(),
        "kem": "ML-KEM-768",
        "kem_public_key_b64": base64.b64encode(public_key).decode(),
        "server_id": P1_ID,
        "server_signing_public_key_b64": base64.b64encode(SERVER_PUBLIC_RAW).decode(),
        "server_signature_b64": base64.b64encode(SERVER_SIGNER.sign(signed)).decode(),
        "expires_in_seconds": HANDSHAKE_TTL,
    }


@app.post("/v1/handshakes/{handshake_id}/complete")
async def complete_handshake(handshake_id: str, request: HandshakeRequest):
    if request.handshake_id != handshake_id:
        raise HTTPException(400, "handshake ID mismatch")
    trusted_key = TRUSTED_CLIENTS.get(request.client_id)
    if trusted_key is None:
        raise HTTPException(401, "unknown client identity")
    redis: Redis = app.state.redis
    cached = await redis.getdel(f"pw:handshake:{handshake_id}")
    if cached is None:
        raise HTTPException(410, "handshake expired or already used")
    try:
        state = json.loads(cached)
        kem_public_key = b64d(state["public_key"])
        challenge = b64d(state["challenge"])
        signature = b64d(request.client_signature_b64)
        ciphertext = b64d(request.ciphertext_b64)
        if len(ciphertext) != ml_kem_768.CIPHERTEXT_SIZE:
            raise ValueError("wrong ML-KEM ciphertext length")
        Ed25519PublicKey.from_public_bytes(trusted_key).verify(
            signature, transcript(handshake_id, request.client_id, kem_public_key) + b"\0" + challenge
        )
        shared_secret = ml_kem_768.decaps(b64d(state["secret_key"]), ciphertext)
    except Exception as exc:
        raise HTTPException(401, "invalid client proof or ML-KEM ciphertext") from exc

    context = transcript(handshake_id, request.client_id, kem_public_key) + ciphertext
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=challenge, info=b"pricewatchin-registration-aes256gcm-v1\0" + context).derive(shared_secret)
    session_id = secrets.token_urlsafe(32)
    await redis.setex(f"pw:session:{session_id}", SESSION_TTL, json.dumps({"client_id": request.client_id, "key": base64.b64encode(key).decode(), "created_at": int(time.time())}))
    proof = hashlib.sha256(b"pricewatchin-server-finished-v1\0" + context + key).digest()
    signed_response = b"pricewatchin-server-finished-v1\0" + session_id.encode() + b"\0" + proof
    return {
        "session_id": session_id,
        "expires_in_seconds": SESSION_TTL,
        "server_proof_b64": base64.b64encode(proof).decode(),
        "server_signature_b64": base64.b64encode(SERVER_SIGNER.sign(signed_response)).decode(),
    }


@app.post("/v1/registrations", status_code=201)
async def register_bank_user(payload: EncryptedRegistration, x_session_id: Annotated[str, Header(alias="X-Session-ID")]):
    redis: Redis = app.state.redis
    # A registration session is single-use, including against encrypted-payload replay.
    raw_session = await redis.getdel(f"pw:session:{x_session_id}")
    if raw_session is None:
        raise HTTPException(401, "unknown or expired session")
    try:
        session = json.loads(raw_session)
        nonce = b64d(payload.nonce_b64)
        ciphertext = b64d(payload.ciphertext_b64)
        if len(nonce) != 12:
            raise ValueError("AES-GCM nonce must be 12 bytes")
        plaintext = AESGCM(b64d(session["key"])).decaps(nonce, ciphertext, AAD_PREFIX + x_session_id.encode())
        registration = json.loads(plaintext)
    except Exception as exc:
        raise HTTPException(400, "registration could not be authenticated or decoded") from exc

    required = {"full_name", "email", "phone", "account_type"}
    if not isinstance(registration, dict) or not required.issubset(registration):
        raise HTTPException(422, "registration must include full_name, email, phone, and account_type")
    full_name, email, phone, account_type = (registration.get(k) for k in ("full_name", "email", "phone", "account_type"))
    if not all(isinstance(v, str) and v.strip() for v in (full_name, email, phone, account_type)):
        raise HTTPException(422, "registration fields must be non-empty strings")
    if len(full_name) > 120 or len(email) > 254 or len(phone) > 32 or len(account_type) > 32:
        raise HTTPException(422, "one or more registration fields are too long")

    user_id = secrets.token_urlsafe(12)
    stored = {"user_id": user_id, "client_id": session["client_id"], "full_name": full_name.strip(), "email": email.strip().lower(), "phone": phone.strip(), "account_type": account_type.strip(), "created_at": int(time.time())}
    # Store an email index atomically to avoid duplicate registrations in Redis.
    email_key = "pw:registration:email:" + hashlib.sha256(stored["email"].encode()).hexdigest()
    created = await redis.set(email_key, user_id, nx=True, ex=60 * 60 * 24 * 365)
    if not created:
        raise HTTPException(409, "email is already registered")
    try:
        await redis.set(f"pw:registration:{user_id}", json.dumps(stored), ex=60 * 60 * 24 * 365)
    except RedisError:
        await redis.delete(email_key)
        raise HTTPException(503, "registration storage is temporarily unavailable")
    return {"user_id": user_id, "status": "registered", "created_at": stored["created_at"]}


@app.get("/v1/bank/registrations")
async def bank_registrations(authorization: Annotated[str | None, Header()] = None, limit: int = 50):
    """Demo bank review endpoint. Protect with BANK_ADMIN_TOKEN; never expose publicly as-is."""
    if not BANK_ADMIN_TOKEN:
        raise HTTPException(503, "BANK_ADMIN_TOKEN is not configured")
    if authorization != f"Bearer {BANK_ADMIN_TOKEN}":
        raise HTTPException(401, "invalid bank admin token")
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    records = []
    async for key in app.state.redis.scan_iter(match="pw:registration:*", count=100):
        if b":email:" in key:
            continue
        raw = await app.state.redis.get(key)
        if raw:
            records.append(json.loads(raw))
    records.sort(key=lambda record: record.get("created_at", 0), reverse=True)
    return {"count": len(records[:limit]), "registrations": records[:limit]}


