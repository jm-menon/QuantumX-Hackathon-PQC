# PriceWatchin PQC bank registration backend

This backend demo models **P1 as the bank API/server** and **P2 as the client gateway**. P2 authenticates itself with a pinned Ed25519 identity, establishes a fresh ML-KEM-768 shared secret with P1, derives an AES-256-GCM key with HKDF-SHA-256, and sends a simplified bank registration encrypted under that key. P1 stores short lived handshake/session state and registrations in Redis.

ML-KEM is a key encapsulation mechanism, not an identity system. Identity comes from Ed25519 keys provisioned out of band: P1 trusts the client key in `TRUSTED_CLIENTS_JSON`; P2 pins P1's public key in `P1_ED25519_PUBLIC_KEY_B64`. Use TLS between services. This is a hackathon backend example, not a complete production banking system; production deployment also needs managed key custody/rotation, authorization and auditing, PII retention controls, rate limits, and operational hardening.

## Configure identities

Generate matching local identities once from the repository root:

```bash
servers/p1/.venv/bin/python scripts/setup_local_identities.py
```

This creates ignored `.env.p1` and `.env.p2` files. They contain the P1 signing key, P2 signing key, P1's trusted P2 key, P2's pin for P1, and a bank review token. The helper refuses to overwrite existing files so identity pins remain stable across restarts. If these files already exist, reuse them. If you intentionally need new identities, remove both env files first and generate a new pair.

For custom deployments, P1 must receive `P1_ED25519_PRIVATE_KEY_B64` and `TRUSTED_CLIENTS_JSON`; P2 must receive `P2_ED25519_PRIVATE_KEY_B64` and `P1_ED25519_PUBLIC_KEY_B64`. P2's client ID must match a key in P1's trusted-client mapping.

## Run locally

Start Redis (for example `redis-server`) and generate the identity files once. Then start the services in two terminals. Stop any already-running P1/P2 processes first so they load the environment files:

```bash
cd servers/p1
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn apps.main:app --env-file ../../.env.p1 --host 0.0.0.0 --port 8001
```

```bash
cd servers/p2
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn apps.main:app --env-file ../../.env.p2 --host 0.0.0.0 --port 8002
```

P1 defaults to `REDIS_URL=redis://localhost:6379/0`. Both services expose `/docs` for the backend API. If you already started either service, stop it and restart it with the generated env file so the signing keys and pins are loaded.

P1 listens on port `8001`; P2 defaults to `P1_URL=http://localhost:8001` and listens on port `8002`. You can override P2's upstream with `P1_URL` if you use another P1 address.

The bank review token is generated in `.env.p1`. The `.env.p1` and `.env.p2` files must stay paired and unchanged between restarts.

## API URLs

With the local commands above, the API base URLs are **P1 `http://localhost:8001`** and **P2 `http://localhost:8002`**. FastAPI's interactive API docs are at `http://localhost:8001/docs` and `http://localhost:8002/docs`.

| Method | URL | Purpose |
| --- | --- | --- |
| `GET` | `http://localhost:8001/health` | P1 health |
| `GET` | `http://localhost:8001/v1/identity` | P1 signing identity and public key |
| `GET` | `http://localhost:8001/v1/qkd/status` | P1 QKD simulation mode |
| `POST` | `http://localhost:8001/v1/handshakes` | Start P1's ML-KEM handshake |
| `POST` | `http://localhost:8001/v1/handshakes/{handshake_id}/complete` | Complete/authenticate a handshake (normally called by P2) |
| `POST` | `http://localhost:8001/v1/registrations` | Submit AES-GCM encrypted registration (normally called by P2) |
| `GET` | `http://localhost:8001/v1/bank/registrations?limit=50` | Bank review list; send `Authorization: Bearer $BANK_ADMIN_TOKEN` |
| `GET` | `http://localhost:8002/health` | P2 health |
| `GET` | `http://localhost:8002/v1/identity` | P2 signing identity and public key |
| `GET` | `http://localhost:8002/v1/qkd/status` | P2 QKD simulation mode |
| `POST` | `http://localhost:8002/v1/register` | Register via P2; sends JSON `{ "registration": { "full_name": "...", "email": "...", "phone": "...", "account_type": "Savings" } }` |

For an end-to-end registration, call **P2** at `POST http://localhost:8002/v1/register` and include the JSON body shown below; P2 drives the authenticated exchange and submits encrypted data to P1. The P1 `/complete` and `/registrations` routes are low-level protocol steps and require the returned handshake ID/session ID, signatures, encrypted body, and headers. Do not call them with an empty path segment or without those values; use P2 `/v1/register` for normal testing.

## Frontend

The React/Vite UI runs at `http://localhost:5173`. In another terminal:

```bash
cd frontend
npm install
npm run dev
```

The UI's **New registration** view submits through P2. The **Bank review** view fetches decrypted records from P1 and prompts for `BANK_ADMIN_TOKEN`. Configure alternate service origins with `VITE_P1_URL` and `VITE_P2_URL` before starting Vite. Both services allow `http://localhost:5173` by default through `CORS_ORIGINS`.

## Optional Qiskit BB84 simulation

The QKD addition is deliberately a **simulation skeleton**. It models BB84 measurements with Qiskit's local `Statevector` simulator and mixes the simulated key with the ML-KEM secret as HKDF input before deriving the AES key. It does not provide real QKD security, a quantum channel, or eavesdropping guarantees. This is only a prototype for fixed nodes; the normal end-user flow remains ML-KEM over the classical service connection.

To turn it on, generate a 32-byte seed and provision the same secret value to P1 and P2 through your local environment or secret manager:

```bash
python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
export QKD_SIMULATION_ENABLED=true
export QKD_SIMULATION_SEED_B64='<generated-base64-seed>'
```

Set those two variables in **both** service environments before starting them. Qiskit is included in both Python requirements files. Both services expose `GET /v1/qkd/status`; P2 also rejects a handshake if P1 and P2 have different key exchange modes. Leave the feature disabled (the default) to use ML-KEM alone.

## Troubleshooting registration

- **P2 says `P1_ED25519_PUBLIC_KEY_B64` is missing:** run `servers/p1/.venv/bin/python scripts/setup_local_identities.py` from the repository root once, then restart P1 with `--env-file ../../.env.p1` and P2 with `--env-file ../../.env.p2` as above.
- **`POST /v1/register` returns 422:** send a JSON body with the `registration` object. In Swagger, click **Try it out** and keep/edit the example body. A request without a body correctly returns 422.
- **`POST /v1/handshakes//complete` returns 404:** the handshake ID path parameter is empty. Use P2 `/v1/register`, which obtains and supplies it automatically.
- **P1 `/v1/registrations` returns 422 for missing fields:** this low-level route requires both `X-Session-ID` and an AES-GCM payload. Use P2 `/v1/register` for a complete client flow.

## Register a user through P2

```bash
curl -X POST http://localhost:8002/v1/register \
  -H 'Content-Type: application/json' \
  -d '{"registration":{"full_name":"Asha Rao","email":"asha@example.com","phone":"+919876543210","account_type":"savings"}}'
```

P2 requests a one-time P1 KEM handshake, verifies P1's identity/signature, encapsulates to P1's ML-KEM public key and signs the transcript. P1 verifies P2 against its configured trust list, decapsulates, derives the same AES key and issues an opaque session ID. P2 verifies P1's key confirmation, encrypts the registration with AES-GCM (including the session ID as associated data), and sends it to P1. P1 rejects reused/expired handshakes, expired sessions, invalid ciphertexts, and duplicate email addresses.

Registration fields are `full_name`, `email`, `phone`, and `account_type`; stored records expire after one year. Handshake private material expires in 120 seconds and session keys in 10 minutes. Redis should be private to the service network and configured with suitable persistence, ACLs, and encryption for the deployment.

## Concurrent load test with Locust

The `locust/locust.py` scenario sends concurrent, unique registrations through both P2 variants, so each simulated client exercises the full handshake and encrypted registration path. It starts one bank-side reader for each P1 variant; each reads its registration list immediately and then once every 60 seconds. Redis uses one-time handshake/session reads and an atomic `SET NX` email index, so concurrent requests do not share handshake state and duplicate emails cannot both be accepted.

The default run uses five registration users per mode and two bank readers, for 12 total users. The two registration classes have fixed counts, so set `--users` to `2 * REGISTRATION_USERS_PER_MODE + 2`.

Install Locust in its own environment and launch the comparison against the Docker ports:

```bash
cd locust
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
P1_QKD_ON_URL=http://localhost:8001 P2_QKD_ON_URL=http://localhost:8002 \
P1_QKD_OFF_URL=http://localhost:8003 P2_QKD_OFF_URL=http://localhost:8004 \
REGISTRATION_USERS_PER_MODE=5 BANK_ADMIN_TOKEN='<value from .env.p1>' \
  .venv/bin/locust -f locust.py --users 12 --spawn-rate 2
```

Replace the token placeholder with the value from `.env.p1`. Open `http://localhost:8089` and start the run. Use `REGISTRATION_USERS_PER_MODE=10` and `--users 22` to double the clients. Stop the run before using generated records as real data. This is a local demo load test, not a capacity or security certification. The Qiskit BB84 simulation is CPU work and is dispatched off each FastAPI event loop; throughput still depends on CPU, Redis, and the selected user count.

## Docker, Prometheus, and Grafana

The root `docker-compose.yml` starts two isolated P1/P2 pairs: QKD simulation on at ports `8001/8002`, and QKD simulation off at `8003/8004`. They use separate Redis databases. The React frontend is available at `http://localhost:5173`, Prometheus at `http://localhost:9090`, and Grafana at `http://localhost:3000` (local demo login `admin` / `admin`). Change the Grafana password with `GRAFANA_ADMIN_PASSWORD` before sharing the stack.

Make sure `.env.p1` and `.env.p2` exist and contain the paired signing identities. The identity setup helper now generates the same random QKD simulation seed for both files. If using older env files without a strong shared seed, add the same newly generated base64 encoding of 32 random bytes to both files as `QKD_SIMULATION_SEED_B64`; do not use an all-zero placeholder. Then build and start the stack:

```bash
docker compose up --build
```

Stop any locally running P1/P2 processes first so their host ports are free.

The provisioned Grafana dashboard is **QKD On vs Off — Registration Latency**. It compares P2's end-to-end `POST /v1/register` p50/p95 and mean duration, plus successful registration rate, grouped by the `qkd_enabled` label. Prometheus scrapes each service's `/metrics` endpoint every five seconds. The duration is end-to-end API processing time (including the P2-to-P1 round trips), not an isolated measurement of only Qiskit's simulator. A short run may not give enough samples for stable percentiles; leave Locust running for several minutes. The benchmark captures performance differences for this prototype, not evidence of a security advantage from simulated QKD.

The Prometheus scrape configuration is [`monitoring/prometheus.yml`](monitoring/prometheus.yml); the Grafana dashboard and provisioning are under `monitoring/grafana/`. Both APIs also expose `/metrics` for local inspection.
