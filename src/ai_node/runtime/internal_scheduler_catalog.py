from copy import deepcopy


SCHEDULE_CATALOG = {
    "interval_seconds": {"name": "interval_seconds", "detail": "Every N seconds (requires integer seconds)"},
    "daily": {"name": "daily", "detail": "Every day at 00:01"},
    "weekly": {"name": "weekly", "detail": "Monday 00:01"},
    "4_times_a_day": {"name": "4_times_a_day", "detail": "00:00, 06:00, 12:00, 18:00"},
    "every_5_minutes": {"name": "every_5_minutes", "detail": "00:05, 00:10, 00:15, ..."},
    "hourly": {"name": "hourly", "detail": "Hourly at :00"},
    "bi_weekly": {"name": "bi_weekly", "detail": "Every 2 weeks"},
    "monthly": {"name": "monthly", "detail": "First day of each month at 00:01"},
    "every_other_day": {"name": "every_other_day", "detail": "Every other day at 00:01"},
    "twice_a_week": {"name": "twice_a_week", "detail": "Monday and Thursday at 00:01"},
    "on_start": {"name": "on_start", "detail": "Runs once after full operational readiness"},
    "every_10_seconds": {"name": "every_10_seconds", "detail": "Every 10 seconds"},
    "heartbeat_5_seconds": {"name": "heartbeat_5_seconds", "detail": "Heartbeat every 5 seconds"},
    "telemetry_60_seconds": {"name": "telemetry_60_seconds", "detail": "Telemetry every 60 seconds"},
}


def schedule_catalog_payload() -> list[dict]:
    return [deepcopy(payload) for payload in SCHEDULE_CATALOG.values()]


def get_schedule_definition(name: str, *, fallback_detail: str | None = None) -> dict:
    normalized = str(name or "").strip()
    payload = deepcopy(SCHEDULE_CATALOG.get(normalized) or {})
    if payload:
        return payload
    return {"name": normalized or "interval_seconds", "detail": str(fallback_detail or "").strip() or None}
