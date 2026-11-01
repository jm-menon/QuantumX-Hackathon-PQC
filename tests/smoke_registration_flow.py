"""Run a P2 -> P1 registration smoke test without a Redis or HTTP server process."""
from __future__ import annotations

import asyncio
import importlib.util
import base64
import json
import os
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SERVERS = ROOT / "servers"
sys.path.insert(0, str(SERVERS))
sys.path.insert(0, str(SERVERS / "p1"))
sys.path.insert(0, str(SERVERS / "p2"))
os.environ["QKD_SIMULATION_ENABLED"] = "false"
os.environ.pop("QKD_SIMULATION_SEED_B64", None)


def create_signing_identity() -> tuple[str, str]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(private).decode(), base64.b64encode(public).decode()


p1_private, p1_public = create_signing_identity()
p2_private, p2_public = create_signing_identity()
os.environ["P1_ED25519_PRIVATE_KEY_B64"] = p1_private
os.environ["TRUSTED_CLIENTS_JSON"] = json.dumps({"p2-demo-client": p2_public})
os.environ["P2_ED25519_PRIVATE_KEY_B64"] = p2_private
os.environ["P1_ED25519_PUBLIC_KEY_B64"] = p1_public
os.environ["P2_CLIENT_ID"] = "p2-demo-client"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


p1 = load_module("p1_smoke_app", SERVERS / "p1/apps/main.py")
p2 = load_module("p2_smoke_app", SERVERS / "p2/apps/main.py")


class MemoryRedis:
    def __init__(self):
        self.values: dict[bytes, bytes] = {}

    @staticmethod
    def _key(key) -> bytes:
        return key if isinstance(key, bytes) else str(key).encode()

    async def setex(self, key, _ttl, value):
        self.values[self._key(key)] = value if isinstance(value, bytes) else str(value).encode()

    async def getdel(self, key):
        return self.values.pop(self._key(key), None)

    async def get(self, key):
        return self.values.get(self._key(key))

    async def set(self, key, value, nx=False, ex=None):
        key = self._key(key)
        if nx and key in self.values:
            return None
        self.values[key] = value if isinstance(value, bytes) else str(value).encode()
        return True

    async def delete(self, key):
        return int(self.values.pop(self._key(key), None) is not None)

    async def scan_iter(self, match="*", count=100):
        del count
        prefix = match.rstrip("*").encode()
        for key in self.values:
            if key.startswith(prefix):
                yield key


async def main():
    redis = MemoryRedis()
    p1.app.state.redis = redis

    p1_transport = httpx.ASGITransport(app=p1.app)
    p2.app.state.http = httpx.AsyncClient(transport=p1_transport, base_url="http://localhost:8001")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=p2.app), base_url="http://localhost:8002") as client:
            openapi = p2.app.openapi()
            body_schema = openapi["paths"]["/v1/register"]["post"]["requestBody"]["content"]["application/json"]["schema"]
            body_example = openapi["components"]["schemas"]["RegisterRequest"] if "$ref" in body_schema else body_schema
            assert body_example.get("examples"), "Swagger should provide a registration JSON example"
            missing_body = await client.post("/v1/register")
            assert missing_body.status_code == 422, "Bodyless registration should be rejected with a useful validation error"
            for suffix in ("one", "two"):
                response = await client.post(
                    "/v1/register",
                    json={
                        "registration": {
                            "full_name": f"Test User {suffix}",
                            "email": f"smoke-{suffix}@example.com",
                            "phone": "+919876543210",
                            "account_type": "savings",
                        }
                    },
                )
                assert response.status_code == 201, response.text
                assert response.json()["status"] == "registered", response.text

        saved = [key for key in redis.values if key.startswith(b"pw:registration:") and b":email:" not in key]
        assert len(saved) == 2, f"Expected two saved registrations; found {len(saved)}"
        print("PASS: two successive P2 registrations completed through P1 and were stored.")
    finally:
        await p2.app.state.http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
