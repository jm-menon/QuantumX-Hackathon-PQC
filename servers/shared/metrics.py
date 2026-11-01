"""Prometheus request metrics shared by the P1 and P2 FastAPI services."""
from __future__ import annotations

from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response


HTTP_REQUESTS = Counter(
    "bank_api_http_requests_total",
    "HTTP requests handled by the bank demo APIs.",
    ("service", "qkd_enabled", "method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "bank_api_http_request_duration_seconds",
    "HTTP request processing time in seconds.",
    ("service", "qkd_enabled", "method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


def instrument_app(app, *, service: str, qkd_enabled: bool) -> None:
    """Record per-route latency/counts; omit /metrics to avoid scrape noise."""
    @app.middleware("http")
    async def collect_http_metrics(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        started = perf_counter()
        status_code = "500"
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            labels = {
                "service": service,
                "qkd_enabled": str(qkd_enabled).lower(),
                "method": request.method,
                "route": route_path,
            }
            HTTP_REQUEST_DURATION.labels(**labels).observe(perf_counter() - started)
            HTTP_REQUESTS.labels(**labels, status_code=status_code).inc()


def prometheus_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
