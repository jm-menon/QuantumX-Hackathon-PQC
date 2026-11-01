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

## Qiskit BB84 simulation

Both API requirements include the actual `qiskit` Python package. When `QKD_SIMULATION_ENABLED=true`, `servers/shared/qkd_simulation.py` runs a local BB84-style simulation using Qiskit's `QuantumCircuit` and `Statevector` measurement sampling. P1 and P2 reproduce the same simulated output from a shared seed and the per-handshake challenge. The simulation's 32-byte output is combined with the ML-KEM shared secret as HKDF input before deriving the AES-256-GCM key.

The local identity setup helper writes `QKD_SIMULATION_ENABLED=true` and one randomly generated, shared `QKD_SIMULATION_SEED_B64` into both ignored env files. Keep the values paired. If using existing env files, make a new seed and copy the exact same value into both `.env.p1` and `.env.p2`:

```bash
python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

To compare with ML-KEM only, set `QKD_SIMULATION_ENABLED=false` on **both** services. The two services must use the same mode or P2 rejects the handshake. Check their active settings with `GET /v1/qkd/status`. This is a local simulation: no qubits are sent between P1 and P2, and it provides no physical QKD or eavesdropping security.

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

### View the benchmark results

1. Start the complete local stack with `docker compose up --build` and wait until all containers are healthy.
2. Confirm the modes: `http://localhost:8001/v1/qkd/status` and `http://localhost:8002/v1/qkd/status` should report enabled; ports `8003` and `8004` should report disabled.
3. Open Prometheus at [`http://localhost:9090/targets`](http://localhost:9090/targets). The four `p1-qkd-on`, `p2-qkd-on`, `p1-qkd-off`, and `p2-qkd-off` targets should show **UP**. Prometheus is collecting data but does not itself provide the provisioned comparison dashboard.
4. Open Grafana at [`http://localhost:3000`](http://localhost:3000). Sign in with `admin` / `admin` for the local-only stack. Choose **Dashboards → QuantumX → QKD On vs Off — Registration Latency**.
5. Start Locust using the command above (from `locust/`). The default spawns five registration users per mode and one bank reader per mode. The bank readers poll immediately and then every minute; registration users continue submitting unique email addresses.
6. Leave the load running for a few minutes. The dashboard refreshes every five seconds; p50/p95 panels use a rolling one-minute Prometheus rate window. The lines may be empty before registrations arrive or while the first window fills.

The main panel reports **p50** (median) and **p95** (95% of measured requests completed within this duration). The mean panel reports the average P2 route duration, and successful registrations per second helps check that a slower latency line is still completing requests. The Prometheus expression for the p95 comparison is:

```promql
histogram_quantile(
  0.95,
  sum by (le, qkd_enabled) (
    rate(bank_api_http_request_duration_seconds_bucket{
      service="p2",
      route="/v1/register"
    }[1m])
  )
)
```

Paste it into the Prometheus query box at `http://localhost:9090/graph` to view the raw time series. The service also records P1 endpoint timings; filter with `service="p1"` to inspect handshake and decrypt/store route durations separately.

The Prometheus scrape configuration is [`monitoring/prometheus.yml`](monitoring/prometheus.yml); the Grafana dashboard and provisioning are under `monitoring/grafana/`. Both APIs also expose `/metrics` for local inspection.

## Deploy the application on Render

The easiest Render setup is one P1 web service, one P2 web service, one Render Key Value datastore, and one static frontend. The repo's Docker Compose file is for local multi-container development; Render deploys each service as its own resource. Render supports Docker-based web services, static sites, and Redis-compatible Key Value datastores. Keep services and Key Value in the same region when possible so server-to-server and cache traffic uses Render's private network. See Render's [Docker deployment guide](https://render.com/docs/docker), [static-site guide](https://render.com/docs/static-sites), [Key Value guide](https://render.com/docs/key-value), and [private-network guide](https://render.com/docs/private-network).

### 1. Push the repository to GitHub

Render needs access to the Git repository. Commit and push the Dockerfiles, frontend, API code, and requirements. Do **not** commit `.env.p1` or `.env.p2`; these contain private signing keys and are ignored by Git. Create matching local identity files once if needed, then copy their values into Render's environment-variable settings rather than uploading the files to the repository.

### 2. Create Render Key Value

In the Render Dashboard choose **New → Key Value**. Choose a region and note the internal connection URL from the service's **Connect** page. Add that value to P1's `REDIS_URL`. The API stores short-lived handshake/session keys and registration records in this datastore. Render's free Key Value plan has no persistence, so records can disappear when the instance restarts; choose a persistent plan if the hosted demo needs registrations to survive restarts. Render Key Value is Redis-compatible and newer instances run Valkey. ([Render Key Value docs](https://render.com/docs/key-value))

### 3. Deploy P1 as a Docker web service

In Render choose **New → Web Service**, connect the repository, and set:

- Runtime: **Docker**
- Dockerfile path: `Dockerfile`
- Docker build context: repository root (`.`)
- Health check path: `/health`
- Region: same as Key Value and P2
- Environment variable `APP_DIR`: `servers/p1`

`APP_DIR` selects the P1 app and requirements in the root Dockerfile. The Dockerfile now listens on Render's injected `PORT` value (Render's default is `10000`) and binds to `0.0.0.0`, as required by Render web services. ([Render web service docs](https://render.com/docs/web-services), [Render environment variables](https://render.com/docs/environment-variables))

Add the following P1 runtime variables in Render. Use the values from the paired local env file when indicated; never put these secret values in Git or README:

| Variable | Value |
|---|---|
| `P1_ED25519_PRIVATE_KEY_B64` | P1 private signing key from `.env.p1` |
| `TRUSTED_CLIENTS_JSON` | P1's trusted-client JSON from `.env.p1` |
| `BANK_ADMIN_TOKEN` | A new long random token, or the local demo token |
| `REDIS_URL` | Render Key Value's internal connection URL |
| `QKD_SIMULATION_ENABLED` | `true` to match the local QKD-on demo |
| `QKD_SIMULATION_SEED_B64` | Same random seed used by P2 |
| `CORS_ORIGINS` | Frontend's exact `https://...onrender.com` origin after creating the static site |

### 4. Deploy P2 as a second Docker web service

Create another web service connected to the same repository and use the same Dockerfile path, build context, region, and `/health` check. Set `APP_DIR=servers/p2`. Add:

| Variable | Value |
|---|---|
| `P2_ED25519_PRIVATE_KEY_B64` | P2 private signing key from `.env.p2` |
| `P1_ED25519_PUBLIC_KEY_B64` | The pinned P1 public signing key from `.env.p2` |
| `P2_CLIENT_ID` | `p2-demo-client` (must match P1's trusted-client mapping) |
| `P1_URL` | P1's public HTTPS URL, e.g. `https://your-p1-name.onrender.com` |
| `QKD_SIMULATION_ENABLED` | Same mode as P1 (`true` for this setup) |
| `QKD_SIMULATION_SEED_B64` | Exactly the same seed as P1 |
| `CORS_ORIGINS` | The frontend's exact `https://...onrender.com` origin |

P1 is a public web service in this setup because the browser-based bank review screen calls P1 directly. P2 can use P1's public HTTPS address, which also works on free web instances. If your plan supports private networking and you configure P1/P2 in the same region, you can instead set `P1_URL` to P1's internal address; Render documents that free web services can send private-network requests but cannot receive them. ([Render private networking](https://render.com/docs/private-network))

### 5. Deploy the React frontend as a static site

Create a **Static Site** from the same Git repository with:

- Build command: `cd frontend && npm ci && npm run build`
- Publish directory: `frontend/dist`
- Build-time variable `VITE_P1_URL`: P1's public HTTPS URL
- Build-time variable `VITE_P2_URL`: P2's public HTTPS URL

Vite bakes `VITE_` variables into the static JavaScript during the build, so set these URLs before deploying and trigger a new build whenever they change. Once Render assigns the frontend URL, set `CORS_ORIGINS` on both APIs to that exact origin, then save and redeploy the API services. The browser needs the public HTTPS URLs; it cannot use Render's private hostnames.

### 6. Verify the deployed flow

After all services show **Live**, check:

```text
https://your-p1-name.onrender.com/health
https://your-p2-name.onrender.com/health
https://your-p1-name.onrender.com/v1/qkd/status
https://your-p2-name.onrender.com/v1/qkd/status
https://your-p1-name.onrender.com/docs
https://your-p2-name.onrender.com/docs
```

Open the static frontend, submit a registration, and use the same `BANK_ADMIN_TOKEN` configured on P1 in the Bank review view. You can also test P2 directly:

```bash
curl -X POST https://your-p2-name.onrender.com/v1/register \
  -H 'Content-Type: application/json' \
  -d '{"registration":{"full_name":"Asha Rao","email":"asha.render@example.com","phone":"+919876543210","account_type":"savings"}}'
```

Watch the Render service logs if a deploy or handshake fails. Common deployment issues are a missing/incorrect `APP_DIR`, missing signing or QKD environment variables, P1 and P2 having different QKD modes/seeds, P2 pointing at the local `localhost:8001` instead of the deployed P1 URL, or CORS not containing the frontend origin.

### Render monitoring and hosted benchmark notes

The Grafana dashboard in this repository is provisioned for the **local Docker Compose** service names. Compose DNS names such as `p2-qkd-on:8000` do not resolve on Render, and Render does not deploy this compose file as a single stack. For the simplest workflow, run the QKD on/off comparison locally using Compose and Grafana. To benchmark on Render, deploy both P1/P2 pairs and isolated Key Value stores, then configure a Prometheus service to scrape each public `/metrics` URL (or use a hosted Prometheus-compatible service); deploy Grafana separately and point it at that Prometheus data source. This uses additional services and resources. Also configure the deployed frontend/backend URLs and CORS origins as described above.

This is a prototype, not a production banking deployment. The sample P1 routes are public in the simplest Render layout, and the demo identities, registration schema, admin access, storage lifecycle, and cryptographic operations need a production security review before use with real customer data.
