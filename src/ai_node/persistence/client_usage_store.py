import ast
import sqlite3
from pathlib import Path

from ai_node.time_utils import local_now_iso


def _month_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 7:
        return normalized[:7]
    return local_now_iso()[:7]


def aggregate_provider_metrics(payload: dict | None) -> dict:
    providers = payload.get("providers") if isinstance(payload, dict) else {}
    totals = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    if not isinstance(providers, dict):
        return totals
    for provider_payload in providers.values():
        models = provider_payload.get("models") if isinstance(provider_payload, dict) else {}
        if not isinstance(models, dict):
            continue
        for model_payload in models.values():
            if not isinstance(model_payload, dict):
                continue
            totals["calls"] += max(int(model_payload.get("successful_requests") or 0), 0)
            totals["prompt_tokens"] += max(int(model_payload.get("prompt_tokens") or 0), 0)
            totals["completion_tokens"] += max(int(model_payload.get("completion_tokens") or 0), 0)
            totals["total_tokens"] += max(int(model_payload.get("total_tokens") or 0), 0)
            totals["cost_usd"] += max(float(model_payload.get("estimated_cost") or 0.0), 0.0)
    totals["cost_usd"] = round(totals["cost_usd"], 10)
    return totals


def aggregate_provider_metrics_by_model(payload: dict | None) -> dict[str, dict]:
    providers = payload.get("providers") if isinstance(payload, dict) else {}
    totals_by_model: dict[str, dict] = {}
    if not isinstance(providers, dict):
        return totals_by_model
    for provider_payload in providers.values():
        models = provider_payload.get("models") if isinstance(provider_payload, dict) else {}
        if not isinstance(models, dict):
            continue
        for model_id, model_payload in models.items():
            if not isinstance(model_payload, dict):
                continue
            normalized_model_id = str(model_id or "").strip() or "unknown-model"
            totals = totals_by_model.setdefault(
                normalized_model_id,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "last_used_at": None,
                },
            )
            totals["calls"] += max(int(model_payload.get("successful_requests") or 0), 0)
            totals["prompt_tokens"] += max(int(model_payload.get("prompt_tokens") or 0), 0)
            totals["completion_tokens"] += max(int(model_payload.get("completion_tokens") or 0), 0)
            totals["total_tokens"] += max(int(model_payload.get("total_tokens") or 0), 0)
            totals["cost_usd"] += max(float(model_payload.get("estimated_cost") or 0.0), 0.0)
    for totals in totals_by_model.values():
        totals["cost_usd"] = round(totals["cost_usd"], 10)
    return totals_by_model


def aggregate_provider_execution_log(log_path: str) -> dict:
    path = Path(log_path)
    totals = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "last_used_at": None,
    }
    if not path.exists():
        return totals
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "[provider-execution]" not in line:
            continue
        timestamp_text = line[:23].strip()
        payload_text = line.split("[provider-execution]", 1)[1].strip()
        try:
            payload = ast.literal_eval(payload_text)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        prompt_tokens = max(int(payload.get("prompt_tokens") or 0), 0)
        completion_tokens = max(int(payload.get("completion_tokens") or 0), 0)
        totals["calls"] += 1
        totals["prompt_tokens"] += prompt_tokens
        totals["completion_tokens"] += completion_tokens
        totals["total_tokens"] += prompt_tokens + completion_tokens
        totals["cost_usd"] += max(float(payload.get("estimated_cost") or 0.0), 0.0)
        iso_timestamp = timestamp_text.replace(" ", "T", 1).replace(",", ".", 1)
        totals["last_used_at"] = iso_timestamp
    totals["cost_usd"] = round(totals["cost_usd"], 10)
    return totals


def aggregate_provider_execution_log_by_model(log_path: str) -> dict[str, dict]:
    path = Path(log_path)
    totals_by_model: dict[str, dict] = {}
    if not path.exists():
        return totals_by_model
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "[provider-execution]" not in line:
            continue
        timestamp_text = line[:23].strip()
        payload_text = line.split("[provider-execution]", 1)[1].strip()
        try:
            payload = ast.literal_eval(payload_text)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        normalized_model_id = str(payload.get("model_id") or "").strip() or "unknown-model"
        totals = totals_by_model.setdefault(
            normalized_model_id,
            {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "last_used_at": None,
            },
        )
        prompt_tokens = max(int(payload.get("prompt_tokens") or 0), 0)
        completion_tokens = max(int(payload.get("completion_tokens") or 0), 0)
        totals["calls"] += 1
        totals["prompt_tokens"] += prompt_tokens
        totals["completion_tokens"] += completion_tokens
        totals["total_tokens"] += prompt_tokens + completion_tokens
        totals["cost_usd"] += max(float(payload.get("estimated_cost") or 0.0), 0.0)
        totals["last_used_at"] = timestamp_text.replace(" ", "T", 1).replace(",", ".", 1)
    for totals in totals_by_model.values():
        totals["cost_usd"] = round(totals["cost_usd"], 10)
    return totals_by_model


class ClientUsageStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_rollups (
                    scope TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    prompt_id TEXT NOT NULL,
                    customer_id TEXT,
                    calls INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, period_key, client_id, prompt_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_usage_rollups (
                    scope TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    prompt_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    customer_id TEXT,
                    calls INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, period_key, client_id, prompt_id, model_id)
                )
                """
            )

    def has_usage_data(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM usage_rollups").fetchone()
        return int(row["count"] or 0) > 0 if row is not None else False

    def has_model_usage_data(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM model_usage_rollups").fetchone()
        return int(row["count"] or 0) > 0 if row is not None else False

    def get_metadata(self, *, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = ?", (str(key),)).fetchone()
        return str(row["value"]) if row is not None else None

    def set_metadata(self, *, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def record_execution(
        self,
        *,
        client_id: str,
        prompt_id: str,
        model_id: str | None = None,
        customer_id: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        used_at: str | None,
    ) -> None:
        self._upsert_usage(
            client_id=client_id,
            prompt_id=prompt_id,
            model_id=model_id,
            customer_id=customer_id,
            calls=1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            used_at=used_at,
        )

    def seed_historical_usage(
        self,
        *,
        client_id: str,
        prompt_id: str,
        model_id: str | None = None,
        include_aggregate: bool = True,
        customer_id: str | None,
        calls: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        used_at: str | None,
    ) -> None:
        if calls <= 0 and total_tokens <= 0 and cost_usd <= 0:
            return
        self._upsert_usage(
            client_id=client_id,
            prompt_id=prompt_id,
            model_id=model_id,
            include_aggregate=include_aggregate,
            customer_id=customer_id,
            calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            used_at=used_at,
        )

    def _upsert_usage(
        self,
        *,
        client_id: str,
        prompt_id: str,
        model_id: str | None = None,
        include_aggregate: bool = True,
        customer_id: str | None,
        calls: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        used_at: str | None,
    ) -> None:
        normalized_client_id = str(client_id or "").strip() or "unknown-client"
        normalized_prompt_id = str(prompt_id or "").strip() or "unattributed-prompt"
        normalized_model_id = str(model_id or "").strip() or None
        normalized_customer_id = str(customer_id or "").strip() or None
        normalized_used_at = str(used_at or local_now_iso()).strip() or local_now_iso()
        month_key = _month_key(normalized_used_at)
        updated_at = local_now_iso()
        with self._connect() as connection:
            for scope, period_key in (("lifetime", "all"), ("monthly", month_key)):
                if include_aggregate:
                    connection.execute(
                        """
                        INSERT INTO usage_rollups(
                            scope, period_key, client_id, prompt_id, customer_id,
                            calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(scope, period_key, client_id, prompt_id) DO UPDATE SET
                            customer_id = COALESCE(excluded.customer_id, usage_rollups.customer_id),
                            calls = usage_rollups.calls + excluded.calls,
                            prompt_tokens = usage_rollups.prompt_tokens + excluded.prompt_tokens,
                            completion_tokens = usage_rollups.completion_tokens + excluded.completion_tokens,
                            total_tokens = usage_rollups.total_tokens + excluded.total_tokens,
                            cost_usd = usage_rollups.cost_usd + excluded.cost_usd,
                            last_used_at = CASE
                                WHEN usage_rollups.last_used_at IS NULL THEN excluded.last_used_at
                                WHEN excluded.last_used_at > usage_rollups.last_used_at THEN excluded.last_used_at
                                ELSE usage_rollups.last_used_at
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (
                            scope,
                            period_key,
                            normalized_client_id,
                            normalized_prompt_id,
                            normalized_customer_id,
                            max(int(calls), 0),
                            max(int(prompt_tokens), 0),
                            max(int(completion_tokens), 0),
                            max(int(total_tokens), 0),
                            max(float(cost_usd), 0.0),
                            normalized_used_at,
                            updated_at,
                        ),
                    )
                if normalized_model_id:
                    connection.execute(
                        """
                        INSERT INTO model_usage_rollups(
                            scope, period_key, client_id, prompt_id, model_id, customer_id,
                            calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(scope, period_key, client_id, prompt_id, model_id) DO UPDATE SET
                            customer_id = COALESCE(excluded.customer_id, model_usage_rollups.customer_id),
                            calls = model_usage_rollups.calls + excluded.calls,
                            prompt_tokens = model_usage_rollups.prompt_tokens + excluded.prompt_tokens,
                            completion_tokens = model_usage_rollups.completion_tokens + excluded.completion_tokens,
                            total_tokens = model_usage_rollups.total_tokens + excluded.total_tokens,
                            cost_usd = model_usage_rollups.cost_usd + excluded.cost_usd,
                            last_used_at = CASE
                                WHEN model_usage_rollups.last_used_at IS NULL THEN excluded.last_used_at
                                WHEN excluded.last_used_at > model_usage_rollups.last_used_at THEN excluded.last_used_at
                                ELSE model_usage_rollups.last_used_at
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (
                            scope,
                            period_key,
                            normalized_client_id,
                            normalized_prompt_id,
                            normalized_model_id,
                            normalized_customer_id,
                            max(int(calls), 0),
                            max(int(prompt_tokens), 0),
                            max(int(completion_tokens), 0),
                            max(int(total_tokens), 0),
                            max(float(cost_usd), 0.0),
                            normalized_used_at,
                            updated_at,
                        ),
                    )

    def summary_payload(self, *, month_key: str | None = None) -> dict:
        selected_month = str(month_key or local_now_iso()[:7]).strip() or local_now_iso()[:7]
        with self._connect() as connection:
            lifetime_rows = connection.execute(
                """
                SELECT client_id, prompt_id, customer_id, calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at
                FROM usage_rollups
                WHERE scope = 'lifetime' AND period_key = 'all'
                ORDER BY cost_usd DESC, total_tokens DESC, calls DESC
                """
            ).fetchall()
            monthly_rows = connection.execute(
                """
                SELECT client_id, prompt_id, customer_id, calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at
                FROM usage_rollups
                WHERE scope = 'monthly' AND period_key = ?
                ORDER BY cost_usd DESC, total_tokens DESC, calls DESC
                """,
                (selected_month,),
            ).fetchall()
            model_lifetime_rows = connection.execute(
                """
                SELECT client_id, prompt_id, model_id, customer_id, calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at
                FROM model_usage_rollups
                WHERE scope = 'lifetime' AND period_key = 'all'
                ORDER BY cost_usd DESC, total_tokens DESC, calls DESC
                """
            ).fetchall()
            model_monthly_rows = connection.execute(
                """
                SELECT client_id, prompt_id, model_id, customer_id, calls, prompt_tokens, completion_tokens, total_tokens, cost_usd, last_used_at
                FROM model_usage_rollups
                WHERE scope = 'monthly' AND period_key = ?
                ORDER BY cost_usd DESC, total_tokens DESC, calls DESC
                """,
                (selected_month,),
            ).fetchall()

        monthly_map = {
            (str(row["client_id"]), str(row["prompt_id"])): dict(row)
            for row in monthly_rows
        }
        model_monthly_map = {
            (str(row["client_id"]), str(row["prompt_id"]), str(row["model_id"])): dict(row)
            for row in model_monthly_rows
        }
        models_by_prompt: dict[tuple[str, str], list[dict]] = {}
        for row in model_lifetime_rows:
            lifetime = dict(row)
            client_id = str(lifetime["client_id"])
            prompt_id = str(lifetime["prompt_id"])
            model_id = str(lifetime["model_id"])
            monthly = model_monthly_map.get((client_id, prompt_id, model_id), {})
            models_by_prompt.setdefault((client_id, prompt_id), []).append(
                {
                    "model_id": model_id,
                    "customer_id": str(lifetime["customer_id"] or "").strip() or None,
                    "lifetime": {
                        "calls": max(int(lifetime["calls"] or 0), 0),
                        "prompt_tokens": max(int(lifetime["prompt_tokens"] or 0), 0),
                        "completion_tokens": max(int(lifetime["completion_tokens"] or 0), 0),
                        "total_tokens": max(int(lifetime["total_tokens"] or 0), 0),
                        "cost_usd": round(max(float(lifetime["cost_usd"] or 0.0), 0.0), 10),
                        "last_used_at": lifetime["last_used_at"],
                    },
                    "current_month": {
                        "calls": max(int(monthly.get("calls") or 0), 0),
                        "prompt_tokens": max(int(monthly.get("prompt_tokens") or 0), 0),
                        "completion_tokens": max(int(monthly.get("completion_tokens") or 0), 0),
                        "total_tokens": max(int(monthly.get("total_tokens") or 0), 0),
                        "cost_usd": round(max(float(monthly.get("cost_usd") or 0.0), 0.0), 10),
                        "last_used_at": monthly.get("last_used_at"),
                    },
                }
            )
        clients: dict[str, dict] = {}
        for row in lifetime_rows:
            lifetime = dict(row)
            client_id = str(lifetime["client_id"])
            prompt_id = str(lifetime["prompt_id"])
            customer_id = str(lifetime["customer_id"] or "").strip()
            monthly = monthly_map.get((client_id, prompt_id), {})
            client_entry = clients.setdefault(
                client_id,
                {
                    "client_id": client_id,
                    "customer_id": customer_id or None,
                    "lifetime": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
                    "current_month": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
                    "prompts": [],
                },
            )
            if client_entry["customer_id"] is None and customer_id:
                client_entry["customer_id"] = customer_id
            for bucket_name, source in (("lifetime", lifetime), ("current_month", monthly)):
                client_entry[bucket_name]["calls"] += max(int(source.get("calls") or 0), 0)
                client_entry[bucket_name]["prompt_tokens"] += max(int(source.get("prompt_tokens") or 0), 0)
                client_entry[bucket_name]["completion_tokens"] += max(int(source.get("completion_tokens") or 0), 0)
                client_entry[bucket_name]["total_tokens"] += max(int(source.get("total_tokens") or 0), 0)
                client_entry[bucket_name]["cost_usd"] += max(float(source.get("cost_usd") or 0.0), 0.0)
            client_entry["prompts"].append(
                {
                    "prompt_id": prompt_id,
                    "customer_id": customer_id or None,
                    "lifetime": {
                        "calls": max(int(lifetime["calls"] or 0), 0),
                        "prompt_tokens": max(int(lifetime["prompt_tokens"] or 0), 0),
                        "completion_tokens": max(int(lifetime["completion_tokens"] or 0), 0),
                        "total_tokens": max(int(lifetime["total_tokens"] or 0), 0),
                        "cost_usd": round(max(float(lifetime["cost_usd"] or 0.0), 0.0), 10),
                        "last_used_at": lifetime["last_used_at"],
                    },
                    "current_month": {
                        "calls": max(int(monthly.get("calls") or 0), 0),
                        "prompt_tokens": max(int(monthly.get("prompt_tokens") or 0), 0),
                        "completion_tokens": max(int(monthly.get("completion_tokens") or 0), 0),
                        "total_tokens": max(int(monthly.get("total_tokens") or 0), 0),
                        "cost_usd": round(max(float(monthly.get("cost_usd") or 0.0), 0.0), 10),
                        "last_used_at": monthly.get("last_used_at"),
                    },
                    "models": sorted(
                        models_by_prompt.get((client_id, prompt_id), []),
                        key=lambda item: item["lifetime"]["cost_usd"],
                        reverse=True,
                    ),
                }
            )

        client_payload = []
        for client in clients.values():
            client["lifetime"]["cost_usd"] = round(client["lifetime"]["cost_usd"], 10)
            client["current_month"]["cost_usd"] = round(client["current_month"]["cost_usd"], 10)
            client["prompts"].sort(key=lambda item: item["lifetime"]["cost_usd"], reverse=True)
            client_payload.append(client)
        client_payload.sort(key=lambda item: item["lifetime"]["cost_usd"], reverse=True)
        return {
            "configured": True,
            "current_month": selected_month,
            "clients": client_payload,
        }
