"""Create ignored local P1/P2 env files with mutually pinned demo identities."""
from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
P1_ENV = ROOT / ".env.p1"
P2_ENV = ROOT / ".env.p2"


def encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def key_pair() -> tuple[str, str]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return encode(private), encode(public)


def main() -> None:
    existing = [path.name for path in (P1_ENV, P2_ENV) if path.exists()]
    if existing:
        raise SystemExit(f"Refusing to overwrite existing identity file(s): {', '.join(existing)}")

    p1_private, p1_public = key_pair()
    p2_private, p2_public = key_pair()
    trusted_clients = json.dumps({"p2-demo-client": p2_public}, separators=(",", ":"))
    admin_token = secrets.token_urlsafe(32)
    P1_ENV.write_text(
        "\n".join(
            [
                f"P1_ED25519_PRIVATE_KEY_B64={p1_private}",
                f"TRUSTED_CLIENTS_JSON='{trusted_clients}'",
                f"BANK_ADMIN_TOKEN={admin_token}",
                "REDIS_URL=redis://localhost:6379/0",
                "CORS_ORIGINS=http://localhost:5173",
                "",
            ]
        ),
        encoding="utf-8",
    )
    P2_ENV.write_text(
        "\n".join(
            [
                f"P2_ED25519_PRIVATE_KEY_B64={p2_private}",
                f"P1_ED25519_PUBLIC_KEY_B64={p1_public}",
                "P2_CLIENT_ID=p2-demo-client",
                "P1_URL=http://localhost:8001",
                "CORS_ORIGINS=http://localhost:5173",
                "",
            ]
        ),
        encoding="utf-8",
    )
    P1_ENV.chmod(0o600)
    P2_ENV.chmod(0o600)
    print("Created .env.p1 and .env.p2 with matching local demo identities.")
    print("These files are gitignored. Keep them unchanged between P1/P2 restarts.")
    print("Start P1 with: cd servers/p1 && .venv/bin/uvicorn apps.main:app --env-file ../../.env.p1 --host 0.0.0.0 --port 8001")
    print("Start P2 with: cd servers/p2 && .venv/bin/uvicorn apps.main:app --env-file ../../.env.p2 --host 0.0.0.0 --port 8002")


if __name__ == "__main__":
    main()
