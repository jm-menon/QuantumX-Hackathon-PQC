# PriceWatchin PQC bank registration backend

This backend demo models **P1 as the bank API/server** and **P2 as the client gateway**. P2 authenticates itself with a pinned Ed25519 identity, establishes a fresh ML-KEM-768 shared secret with P1, derives an AES-256-GCM key with HKDF-SHA-256, and sends a simplified bank registration encrypted under that key. P1 stores short lived handshake/session state and registrations in Redis.

ML-KEM is a key encapsulation mechanism, not an identity system. Identity comes from Ed25519 keys provisioned out of band: P1 trusts the client key in `TRUSTED_CLIENTS_JSON`; P2 pins P1's public key in `P1_ED25519_PUBLIC_KEY_B64`. Use TLS between services. This is a hackathon backend example, not a complete production banking system; production deployment also needs managed key custody/rotation, authorization and auditing, PII retention controls, rate limits, and operational hardening.

## Configure identities

Generate one Ed25519 seed for P1 and one for P2 using Python:

```bash
python -c 'import base64; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization; k=Ed25519PrivateKey.generate(); print("P1_ED25519_PRIVATE_KEY_B64="+base64.b64encode(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()); print("P1_ED25519_PUBLIC_KEY_B64="+base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())'
```

Run it again for P2, using the resulting seed as `P2_ED25519_PRIVATE_KEY_B64` and public key in P1's trusted client mapping. Example configuration (replace the values):

```bash
export P1_ED25519_PRIVATE_KEY_B64='...'
export P2_ED25519_PRIVATE_KEY_B64='...'
export P1_ED25519_PUBLIC_KEY_B64='...'
export TRUSTED_CLIENTS_JSON='{"p2-demo-client":"<P2 public key base64>"}'
```

P1 prints its public key at `GET /v1/identity`; compare that value with the configured P2 pin. The generated default keys are only for local experimentation: P1's key changes on restart and P2's key changes on restart unless the seeds above are configured.

## Run locally

Start Redis (for example `redis-server`), then in two terminals:

```bash
cd servers/p1
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn apps.main:app --host 0.0.0.0 --port 8001
```

```bash
cd servers/p2
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export P1_URL=http://localhost:8001
uvicorn apps.main:app --host 0.0.0.0 --port 8002
```

P1 defaults to `REDIS_URL=redis://localhost:6379/0`. P2 needs all identity environment values described above. Both services expose `/docs` for the backend API.

## Register a user through P2

```bash
curl -X POST http://localhost:8001/v1/register \
  -H 'Content-Type: application/json' \
  -d '{"registration":{"full_name":"Asha Rao","email":"asha@example.com","phone":"+919876543210","account_type":"savings"}}'
```

P2 requests a one-time P1 KEM handshake, verifies P1's identity/signature, encapsulates to P1's ML-KEM public key and signs the transcript. P1 verifies P2 against its configured trust list, decapsulates, derives the same AES key and issues an opaque session ID. P2 verifies P1's key confirmation, encrypts the registration with AES-GCM (including the session ID as associated data), and sends it to P1. P1 rejects reused/expired handshakes, expired sessions, invalid ciphertexts, and duplicate email addresses.

Registration fields are `full_name`, `email`, `phone`, and `account_type`; stored records expire after one year. Handshake private material expires in 120 seconds and session keys in 10 minutes. Redis should be private to the service network and configured with suitable persistence, ACLs, and encryption for the deployment.
