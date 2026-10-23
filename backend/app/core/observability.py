from prometheus_client import Counter, Gauge, Histogram

AUTH_EVENTS = Counter(
    "wbs_auth_events_total",
    "Authentication and authorization security events.",
    ("event_type", "outcome"),
)
HTTP_REQUESTS = Counter(
    "wbs_http_requests_total",
    "Completed API requests.",
    ("method", "route", "status_class"),
)
HTTP_REQUEST_DURATION = Histogram(
    "wbs_http_request_duration_seconds",
    "API request duration in seconds.",
    ("method", "route"),
)
MAINTENANCE_RUNS = Counter(
    "wbs_maintenance_runs_total",
    "Maintenance job outcomes.",
    ("outcome",),
)
REFRESH_SESSIONS = Gauge(
    "wbs_refresh_sessions",
    "Refresh session records by state.",
    ("state",),
)
MIGRATION_AT_HEAD = Gauge(
    "wbs_migration_at_head",
    "Whether the database migration revision is at the application head.",
)


def record_auth_event(event_type: str, success: bool) -> None:
    AUTH_EVENTS.labels(event_type=event_type, outcome="success" if success else "failure").inc()


def record_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    status_class = f"{status_code // 100}xx"
    HTTP_REQUESTS.labels(method=method, route=route, status_class=status_class).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)
