import asyncio
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path


class IdempotencyConflictError(ValueError):
    pass


class ExecutionIdempotencyStore:
    def __init__(self, *, path: str, retention_seconds: int = 86400) -> None:
        self._path = Path(path)
        self._retention_seconds = max(int(retention_seconds), 60)
        self._lock = asyncio.Lock()
        self._records = self._load()
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}

    @staticmethod
    def request_hash(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _scope_key(*, caller_id: str, idempotency_key: str) -> str:
        return hashlib.sha256(f"{caller_id}\0{idempotency_key}".encode("utf-8")).hexdigest()

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("records") if isinstance(payload, dict) else None
        return dict(records) if isinstance(records, dict) else {}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(json.dumps({"version": 1, "records": self._records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or ""))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _prune(self, *, now: datetime) -> None:
        expired = [key for key, record in self._records.items() if (self._parse_time(record.get("expires_at")) or now) <= now]
        for key in expired:
            self._records.pop(key, None)
        if expired:
            self._persist()

    async def execute(self, *, caller_id: str, idempotency_key: str, request_payload: dict, operation):
        caller = str(caller_id or "").strip()
        key = str(idempotency_key or "").strip()
        if not caller or not key:
            return await operation()
        scope_key = self._scope_key(caller_id=caller, idempotency_key=key)
        fingerprint = self.request_hash(request_payload)
        owner = False
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._prune(now=now)
            record = self._records.get(scope_key)
            if isinstance(record, dict):
                if record.get("request_hash") != fingerprint:
                    raise IdempotencyConflictError("idempotency_key_conflict")
                return deepcopy(record.get("response"))
            pending = self._pending.get(scope_key)
            if pending is not None:
                if pending[0] != fingerprint:
                    raise IdempotencyConflictError("idempotency_key_conflict")
                future = pending[1]
            else:
                future = asyncio.get_running_loop().create_future()
                self._pending[scope_key] = (fingerprint, future)
                owner = True
        if not owner:
            return deepcopy(await future)
        try:
            response = await operation()
        except BaseException as exc:
            async with self._lock:
                self._pending.pop(scope_key, None)
                if not future.done():
                    future.set_exception(exc)
                    future.exception()
            raise
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._records[scope_key] = {
                "caller_id": caller,
                "request_hash": fingerprint,
                "response": deepcopy(response),
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=self._retention_seconds)).isoformat(),
            }
            self._persist()
            self._pending.pop(scope_key, None)
            if not future.done():
                future.set_result(deepcopy(response))
        return response
