from datetime import datetime, timedelta, timezone

from ai_node.time_utils import ensure_local_timezone, local_now


def _parse_iso_timestamp(value: object):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return ensure_local_timezone(parsed)


def evaluate_governance_freshness(governance_bundle: dict | None, *, now: datetime | None = None) -> dict:
    now_local = ensure_local_timezone(now) if isinstance(now, datetime) else local_now()
    now_utc = now_local.astimezone(timezone.utc)
    if not isinstance(governance_bundle, dict):
        return {
            "state": "unknown",
            "active_governance_version": None,
            "issued_timestamp": None,
            "last_sync_time": None,
            "next_refresh_due_at": None,
            "max_stale_at": None,
            "reason": "missing_governance_bundle",
        }

    policy_version = str(governance_bundle.get("policy_version") or "").strip() or None
    issued_timestamp = str(governance_bundle.get("issued_timestamp") or "").strip() or None
    last_sync_time = str(governance_bundle.get("synced_at") or "").strip() or None
    refresh_expectations = governance_bundle.get("refresh_expectations")
    refresh_expectations = refresh_expectations if isinstance(refresh_expectations, dict) else {}
    recommended_interval_seconds = int(refresh_expectations.get("recommended_interval_seconds") or 900)
    max_stale_seconds = int(
        refresh_expectations.get("max_stale_seconds") or max(recommended_interval_seconds * 4, 3600)
    )

    sync_dt = _parse_iso_timestamp(last_sync_time)
    if sync_dt is None:
        return {
            "state": "unknown",
            "active_governance_version": policy_version,
            "issued_timestamp": issued_timestamp,
            "last_sync_time": last_sync_time,
            "next_refresh_due_at": None,
            "max_stale_at": None,
            "reason": "invalid_synced_at",
        }

    sync_utc = sync_dt.astimezone(timezone.utc)
    next_refresh_due_at_utc = sync_utc + timedelta(seconds=max(recommended_interval_seconds, 1))
    max_stale_at_utc = sync_utc + timedelta(seconds=max(max_stale_seconds, 1))
    state = "fresh" if now_utc <= max_stale_at_utc else "stale"
    return {
        "state": state,
        "active_governance_version": policy_version,
        "issued_timestamp": issued_timestamp,
        "last_sync_time": sync_dt.isoformat(),
        "next_refresh_due_at": next_refresh_due_at_utc.astimezone().isoformat(),
        "max_stale_at": max_stale_at_utc.astimezone().isoformat(),
        "reason": None,
    }
