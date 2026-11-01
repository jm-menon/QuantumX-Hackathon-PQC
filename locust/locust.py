"""Concurrent P2 registrations plus one bank-side poller.

Run from this directory with BANK_ADMIN_TOKEN set from .env.p1, for example:
    locust -f locust.py --users 11 --spawn-rate 2

Ten or more simulated client users exercise the complete P2 -> P1 flow. One
fixed bank user reads P1's registration list immediately and then once a minute.
"""
from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, constant, task


P1_URL = os.getenv("P1_URL", "http://localhost:8001").rstrip("/")
P2_URL = os.getenv("P2_URL", "http://localhost:8002").rstrip("/")
BANK_ADMIN_TOKEN = os.getenv("BANK_ADMIN_TOKEN", "")


class RegistrationClient(HttpUser):
    """Each user repeatedly creates a unique account through P2."""

    host = P2_URL
    wait_time = between(0.5, 1.5)
    weight = 10

    @task
    def register_account(self) -> None:
        unique_id = uuid.uuid4().hex
        payload = {
            "registration": {
                "full_name": f"Load Test {unique_id[:8]}",
                "email": f"load-{unique_id}@example.com",
                "phone": f"+1555{unique_id[:7]}",
                "account_type": "savings",
            }
        }
        with self.client.post(
            "/v1/register",
            json=payload,
            name="POST /v1/register",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"HTTP {response.status_code}: {response.text[:300]}")
                return
            try:
                result = response.json()
            except ValueError:
                response.failure("P2 returned a non-JSON response")
                return
            if result.get("status") != "registered" or not result.get("user_id"):
                response.failure(f"Unexpected registration response: {result}")
                return
            response.success()


class BankRegistrationReader(HttpUser):
    """One bank user polls the P1 review endpoint every 60 seconds."""

    host = P1_URL
    fixed_count = 1
    wait_time = constant(60)

    def on_start(self) -> None:
        if not BANK_ADMIN_TOKEN:
            self.environment.runner.quit()
            raise RuntimeError(
                "Set BANK_ADMIN_TOKEN from .env.p1 before starting Locust; "
                "the bank review endpoint requires it."
            )

    @task
    def read_registration_list(self) -> None:
        with self.client.get(
            "/v1/bank/registrations?limit=200",
            headers={"Authorization": f"Bearer {BANK_ADMIN_TOKEN}"},
            name="GET /v1/bank/registrations",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text[:300]}")
                return
            try:
                result = response.json()
            except ValueError:
                response.failure("P1 returned a non-JSON response")
                return
            if not isinstance(result.get("registrations"), list):
                response.failure("P1 response has no registrations list")
                return
            response.success()
