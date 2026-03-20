from datetime import datetime, timezone


def local_now() -> datetime:
    return datetime.now().astimezone()


def local_now_iso() -> str:
    return local_now().isoformat()


def ensure_local_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone()
    return value.astimezone()
