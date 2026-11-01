"""Compare concurrent registration latency with Qiskit QKD on vs off.

Run `--users` as (2 * REGISTRATION_USERS_PER_MODE) + 2. The two extra users
are one bank reader for each mode; both poll once per minute.
"""
from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, constant, task


P1_QKD_ON_URL = os.getenv("P1_QKD_ON_URL", "http://localhost:8001").rstrip("/")
P1_QKD_OFF_URL = os.getenv("P1_QKD_OFF_URL", "http://localhost:8003").rstrip("/")
P2_QKD_ON_URL = os.getenv("P2_QKD_ON_URL", "http://localhost:8002").rstrip("/")
P2_QKD_OFF_URL = os.getenv("P2_QKD_OFF_URL", "http://localhost:8004").rstrip("/")
BANK_ADMIN_TOKEN = os.getenv("BANK_ADMIN_TOKEN", "")
REGISTRATION_USERS_PER_MODE = max(1, int(os.getenv("REGISTRATION_USERS_PER_MODE", "5")))


class RegistrationScenario(HttpUser):
    abstract = True
    wait_time = between(0.5, 1.5)

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
        mode = "QKD on" if self.qkd_enabled else "QKD off"
        with self.client.post(
            "/v1/register",
            json=payload,
            name=f"POST /v1/register ({mode})",
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


class RegistrationQKDOn(RegistrationScenario):
    """Traffic to the Qiskit BB84 simulation enabled pair."""

    abstract = False
    host = P2_QKD_ON_URL
    qkd_enabled = True
    fixed_count = REGISTRATION_USERS_PER_MODE


class RegistrationQKDOff(RegistrationScenario):
    """Traffic to the ML-KEM-only pair."""

    abstract = False
    host = P2_QKD_OFF_URL
    qkd_enabled = False
    fixed_count = REGISTRATION_USERS_PER_MODE


class BankReaderScenario(HttpUser):
    abstract = True
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
        mode = "QKD on" if self.qkd_enabled else "QKD off"
        with self.client.get(
            "/v1/bank/registrations?limit=200",
            headers={"Authorization": f"Bearer {BANK_ADMIN_TOKEN}"},
            name=f"GET /v1/bank/registrations ({mode})",
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


class BankReaderQKDOn(BankReaderScenario):
    abstract = False
    host = P1_QKD_ON_URL
    qkd_enabled = True
    fixed_count = 1


class BankReaderQKDOff(BankReaderScenario):
    abstract = False
    host = P1_QKD_OFF_URL
    qkd_enabled = False
    fixed_count = 1
