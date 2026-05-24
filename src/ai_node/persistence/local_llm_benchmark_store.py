import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse
from ai_node.time_utils import local_now_iso


DEFAULT_LOCAL_LLM_BENCHMARK_DB_PATH = ".run/local_llm_benchmarks.db"
DEFAULT_LOCAL_LLM_BENCHMARK_MODELS = [
    "qwen3-8b-q4_k_m",
    "qwen3-14b-q4_k_m",
    "gemma-3-12b-it-q4_k_m",
    "mistral-nemo-instruct-2407-q4_k_m",
]
DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS = ["prompt.email.classifier"]


def parse_structured_output_summary(output_text: str | None) -> dict[str, Any]:
    empty = {"label": None, "confidence": None, "reasoning": None}
    normalized = str(output_text or "").strip()
    if not normalized:
        return empty
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return empty
    if not isinstance(payload, dict):
        return empty
    confidence = payload.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return {
        "label": str(payload.get("label") or "").strip() or None,
        "confidence": confidence,
        "reasoning": str(
            payload.get("rationale")
            or payload.get("reasoning")
            or payload.get("reason")
            or payload.get("explanation")
            or ""
        ).strip()
        or None,
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _average(values: list[float | None]) -> float | None:
    normalized = [float(value) for value in values if value is not None]
    if not normalized:
        return None
    return sum(normalized) / len(normalized)


def local_llm_benchmark_prompt_allowed(prompt_id: str | None) -> bool:
    normalized = str(prompt_id or "").strip()
    return normalized in set(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS)


class LocalLLMBenchmarkStore:
    def __init__(self, *, path: str = DEFAULT_LOCAL_LLM_BENCHMARK_DB_PATH, logger=None) -> None:
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
                CREATE TABLE IF NOT EXISTS benchmark_records (
                    record_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_provider TEXT NOT NULL,
                    source_model TEXT NOT NULL,
                    task_family TEXT NOT NULL,
                    prompt_id TEXT,
                    prompt_version TEXT,
                    trace_id TEXT,
                    request_payload_json TEXT NOT NULL,
                    source_response_json TEXT NOT NULL,
                    source_output_text TEXT,
                    source_label TEXT,
                    source_confidence REAL,
                    source_reasoning TEXT,
                    correct_label TEXT,
                    correction_note TEXT,
                    source_usage_json TEXT NOT NULL,
                    source_latency_ms REAL,
                    source_cost_usd REAL,
                    source_raw_provider_response_ref TEXT,
                    input_snippet TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_model_results (
                    record_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    latency_ms REAL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    output_text TEXT,
                    label TEXT,
                    confidence REAL,
                    reasoning TEXT,
                    error TEXT,
                    vram_used_mib REAL,
                    vram_delta_mib REAL,
                    gpu_util_percent REAL,
                    load_seconds REAL,
                    PRIMARY KEY (record_id, model_id),
                    FOREIGN KEY (record_id) REFERENCES benchmark_records(record_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_benchmark_model_status ON benchmark_model_results(status, model_id, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                connection=connection,
                table="benchmark_model_results",
                column="gpu_util_percent",
                definition="REAL",
            )
            self._ensure_column(connection=connection, table="benchmark_model_results", column="reasoning", definition="TEXT")
            self._ensure_column(connection=connection, table="benchmark_records", column="source_reasoning", definition="TEXT")
            self._ensure_column(connection=connection, table="benchmark_records", column="correct_label", definition="TEXT")
            self._ensure_column(connection=connection, table="benchmark_records", column="correction_note", definition="TEXT")

    @staticmethod
    def _ensure_column(*, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def configured_model_ids(value: str | None = None) -> list[str]:
        raw = str(value or "").strip()
        if not raw:
            return list(DEFAULT_LOCAL_LLM_BENCHMARK_MODELS)
        model_ids = [item.strip() for item in raw.split(",") if item.strip()]
        deduped: list[str] = []
        for model_id in model_ids:
            if model_id not in deduped:
                deduped.append(model_id)
        return deduped or list(DEFAULT_LOCAL_LLM_BENCHMARK_MODELS)

    def capture_enabled(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM benchmark_metadata WHERE key = 'capture_enabled'"
            ).fetchone()
        if row is None:
            return True
        return str(row["value"] or "").strip().lower() not in {"0", "false", "no", "off"}

    def set_capture_enabled(self, *, enabled: bool) -> dict:
        value = "1" if bool(enabled) else "0"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO benchmark_metadata(key, value)
                VALUES('capture_enabled', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (value,),
            )
        return {"capture_enabled": bool(enabled)}

    def record_openai_execution(
        self,
        *,
        request: UnifiedExecutionRequest,
        response: UnifiedExecutionResponse,
        model_ids: list[str] | None = None,
    ) -> str | None:
        if str(response.provider_id or "").strip().lower() != "openai":
            return None
        if not self.capture_enabled():
            return None
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        prompt_id = str(metadata.get("prompt_id") or "").strip()
        if not local_llm_benchmark_prompt_allowed(prompt_id):
            return None
        now = local_now_iso()
        request_payload = request.model_dump(mode="json")
        response_payload = response.model_dump(mode="json")
        prompt_text = self._request_input_text(request_payload)
        identity_payload = {
            "created_at": now,
            "provider": response.provider_id,
            "model": response.model_id,
            "request": request_payload,
            "response_ref": response.raw_provider_response_ref,
        }
        digest = hashlib.sha256(_json_dumps(identity_payload).encode("utf-8")).hexdigest()[:24]
        record_id = f"openai-{digest}"
        output_summary = parse_structured_output_summary(response.output_text)
        usage_payload = response.usage.model_dump(mode="json")
        target_model_ids = model_ids or list(DEFAULT_LOCAL_LLM_BENCHMARK_MODELS)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO benchmark_records(
                    record_id, created_at, updated_at, source_provider, source_model,
                    task_family, prompt_id, prompt_version, trace_id, request_payload_json,
                    source_response_json, source_output_text, source_label, source_confidence,
                    source_reasoning, correct_label, correction_note,
                    source_usage_json, source_latency_ms, source_cost_usd, source_raw_provider_response_ref,
                    input_snippet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO NOTHING
                """,
                (
                    record_id,
                    now,
                    now,
                    str(response.provider_id or "").strip(),
                    str(response.model_id or "").strip(),
                    str(request.task_family or "").strip(),
                    str(metadata.get("prompt_id") or "").strip() or None,
                    str(metadata.get("prompt_version") or "").strip() or None,
                    str(metadata.get("trace_id") or "").strip() or None,
                    _json_dumps(request_payload),
                    _json_dumps(response_payload),
                    response.output_text,
                    output_summary["label"],
                    output_summary["confidence"],
                    output_summary["reasoning"],
                    None,
                    None,
                    _json_dumps(usage_payload),
                    float(response.latency_ms or 0.0),
                    float(response.estimated_cost or 0.0) if response.estimated_cost is not None else None,
                    response.raw_provider_response_ref,
                    prompt_text[:500],
                ),
            )
            for model_id in target_model_ids:
                normalized_model_id = str(model_id or "").strip()
                if not normalized_model_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO benchmark_model_results(record_id, model_id, status, created_at, updated_at)
                    VALUES (?, ?, 'pending', ?, ?)
                    ON CONFLICT(record_id, model_id) DO NOTHING
                    """,
                    (record_id, normalized_model_id, now, now),
                )
        return record_id

    def summary_payload(self, *, limit: int = 25) -> dict:
        prompt_placeholders = ",".join("?" for _ in DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS)
        with self._connect() as connection:
            record_rows = connection.execute(
                f"""
                SELECT * FROM benchmark_records
                WHERE prompt_id IN ({prompt_placeholders})
                ORDER BY
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM benchmark_model_results m
                            WHERE m.record_id = benchmark_records.record_id
                              AND m.status != 'pending'
                        )
                        THEN 0
                        ELSE 1
                    END,
                    created_at DESC
                LIMIT ?
                """,
                (*DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS, max(int(limit), 0)),
            ).fetchall()
            result_rows = connection.execute(
                """
                SELECT * FROM benchmark_model_results
                WHERE record_id IN ({})
                ORDER BY model_id
                """.format(",".join("?" for _ in record_rows) or "NULL"),
                tuple(row["record_id"] for row in record_rows),
            ).fetchall() if record_rows else []
            status_rows = connection.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE r.prompt_id IN ({prompt_placeholders})
                GROUP BY status
                """,
                tuple(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchall()
            model_status_rows = connection.execute(
                f"""
                SELECT m.model_id, m.status, COUNT(*) AS count
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE r.prompt_id IN ({prompt_placeholders})
                GROUP BY m.model_id, m.status
                """,
                tuple(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchall()
            running_rows = connection.execute(
                f"""
                SELECT m.record_id, m.model_id, m.started_at, r.prompt_id, r.task_family
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE m.status = 'running'
                  AND r.prompt_id IN ({prompt_placeholders})
                ORDER BY m.started_at ASC
                """,
                tuple(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchall()
            all_record_rows = connection.execute(
                f"""
                SELECT * FROM benchmark_records
                WHERE prompt_id IN ({prompt_placeholders})
                """,
                tuple(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchall()
            all_result_rows = connection.execute(
                f"""
                SELECT m.*, r.prompt_id, r.task_family, r.source_label, r.source_confidence,
                       r.source_latency_ms, r.correct_label
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE r.prompt_id IN ({prompt_placeholders})
                ORDER BY m.model_id
                """,
                tuple(DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchall()

        results_by_record: dict[str, list[dict]] = {}
        for row in result_rows:
            results_by_record.setdefault(str(row["record_id"]), []).append(self._result_row_payload(row))
        model_status_counts: dict[str, dict[str, int]] = {}
        for row in model_status_rows:
            model_counts = model_status_counts.setdefault(str(row["model_id"]), {})
            model_counts[str(row["status"])] = int(row["count"] or 0)
        return {
            "configured": True,
            "path": str(self._path),
            "generated_at": local_now_iso(),
            "capture_enabled": self.capture_enabled(),
            "status_counts": {str(row["status"]): int(row["count"] or 0) for row in status_rows},
            "model_status_counts": model_status_counts,
            "model_summaries": self._model_summary_payload(record_rows=all_record_rows, result_rows=all_result_rows),
            "running": [
                {
                    "record_id": str(row["record_id"]),
                    "model_id": row["model_id"],
                    "started_at": row["started_at"],
                    "prompt_id": row["prompt_id"],
                    "task_family": row["task_family"],
                }
                for row in running_rows
            ],
            "comparisons": [
                {
                    "record_id": str(row["record_id"]),
                    "created_at": row["created_at"],
                    "task_family": row["task_family"],
                    "prompt_id": row["prompt_id"],
                    "prompt_version": row["prompt_version"],
                    "input_snippet": row["input_snippet"],
                    "openai": {
                        "provider_id": row["source_provider"],
                        "model_id": row["source_model"],
                        "latency_ms": row["source_latency_ms"],
                        "estimated_cost": row["source_cost_usd"],
                        "usage": _json_loads(row["source_usage_json"], {}),
                        "output_text": row["source_output_text"],
                        "label": row["source_label"],
                        "confidence": row["source_confidence"],
                        "reasoning": row["source_reasoning"],
                    },
                    "correct_label": row["correct_label"],
                    "correction_note": row["correction_note"],
                    "local_results": results_by_record.get(str(row["record_id"]), []),
                }
                for row in record_rows
            ],
        }

    @staticmethod
    def _model_summary_payload(*, record_rows: list[sqlite3.Row], result_rows: list[sqlite3.Row]) -> list[dict]:
        prompt_names = sorted(
            {
                str(row["prompt_id"] or row["task_family"] or "unattributed")
                for row in record_rows
            }
        )
        model_ids = sorted({str(row["model_id"]) for row in result_rows if str(row["model_id"] or "").strip()})
        summaries: list[dict] = []
        for prompt_name in prompt_names:
            prompt_records = [
                row
                for row in record_rows
                if str(row["prompt_id"] or row["task_family"] or "unattributed") == prompt_name
            ]
            openai_matches = 0
            openai_scores: list[float | None] = []
            openai_latencies: list[float | None] = []
            for row in prompt_records:
                target_label = str(row["correct_label"] or row["source_label"] or "").strip().lower()
                source_label = str(row["source_label"] or "").strip().lower()
                if target_label and source_label and target_label == source_label:
                    openai_matches += 1
                openai_scores.append(float(row["source_confidence"]) if row["source_confidence"] is not None else None)
                openai_latencies.append(float(row["source_latency_ms"]) if row["source_latency_ms"] is not None else None)
            summaries.append(
                {
                    "promptName": prompt_name,
                    "modelId": "__openai__",
                    "completed": len(prompt_records),
                    "matchRate": openai_matches / len(prompt_records) if prompt_records else None,
                    "avgScoreDelta": None,
                    "avgLatency": _average(openai_latencies),
                    "avgVram": None,
                    "avgGpu": None,
                }
            )
            for model_id in model_ids:
                completed_rows = [
                    row
                    for row in result_rows
                    if str(row["model_id"]) == model_id
                    and str(row["status"]) == "completed"
                    and str(row["prompt_id"] or row["task_family"] or "unattributed") == prompt_name
                ]
                matched = 0
                score_deltas: list[float | None] = []
                latencies: list[float | None] = []
                vram_values: list[float | None] = []
                gpu_values: list[float | None] = []
                for row in completed_rows:
                    target_label = str(row["correct_label"] or row["source_label"] or "").strip().lower()
                    local_label = str(row["label"] or "").strip().lower()
                    if target_label and local_label and target_label == local_label:
                        matched += 1
                    local_confidence = float(row["confidence"]) if row["confidence"] is not None else None
                    source_confidence = float(row["source_confidence"]) if row["source_confidence"] is not None else None
                    score_deltas.append(
                        local_confidence - source_confidence
                        if local_confidence is not None and source_confidence is not None
                        else None
                    )
                    latencies.append(float(row["latency_ms"]) if row["latency_ms"] is not None else None)
                    vram = row["vram_used_mib"] if row["vram_used_mib"] is not None else row["vram_delta_mib"]
                    vram_values.append(float(vram) if vram is not None else None)
                    gpu_values.append(float(row["gpu_util_percent"]) if row["gpu_util_percent"] is not None else None)
                summaries.append(
                    {
                        "promptName": prompt_name,
                        "modelId": model_id,
                        "completed": len(completed_rows),
                        "matchRate": matched / len(completed_rows) if completed_rows else None,
                        "avgScoreDelta": _average(score_deltas),
                        "avgLatency": _average(latencies),
                        "avgVram": _average(vram_values),
                        "avgGpu": _average(gpu_values),
                    }
                )
        return summaries

    def pending_count_for_models(self, *, model_ids: list[str]) -> int:
        normalized = [str(model_id or "").strip() for model_id in model_ids if str(model_id or "").strip()]
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        prompt_placeholders = ",".join("?" for _ in DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE m.status = 'pending'
                  AND m.model_id IN ({placeholders})
                  AND r.prompt_id IN ({prompt_placeholders})
                """,
                tuple(normalized + DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchone()
        return int(row["count"] or 0) if row is not None else 0

    def pending_count_for_model(self, *, model_id: str) -> int:
        return self.pending_count_for_models(model_ids=[model_id])

    def running_count_for_models(self, *, model_ids: list[str]) -> int:
        normalized = [str(model_id or "").strip() for model_id in model_ids if str(model_id or "").strip()]
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        prompt_placeholders = ",".join("?" for _ in DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM benchmark_model_results m
                JOIN benchmark_records r ON r.record_id = m.record_id
                WHERE m.status = 'running'
                  AND m.model_id IN ({placeholders})
                  AND r.prompt_id IN ({prompt_placeholders})
                """,
                tuple(normalized + DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchone()
        return int(row["count"] or 0) if row is not None else 0

    def running_count_for_model(self, *, model_id: str) -> int:
        return self.running_count_for_models(model_ids=[model_id])

    def set_correct_label(self, *, record_id: str, correct_label: str | None, note: str | None = None) -> dict:
        normalized_record_id = str(record_id or "").strip()
        normalized_label = str(correct_label or "").strip() or None
        normalized_note = str(note or "").strip() or None
        if not normalized_record_id:
            raise ValueError("record_id_required")
        now = local_now_iso()
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE benchmark_records
                SET correct_label = ?, correction_note = ?, updated_at = ?
                WHERE record_id = ?
                """,
                (normalized_label, normalized_note, now, normalized_record_id),
            ).rowcount
        if updated != 1:
            raise ValueError("benchmark_record_not_found")
        return {"record_id": normalized_record_id, "correct_label": normalized_label, "correction_note": normalized_note}

    def claim_next_pending(self, *, model_id: str) -> dict | None:
        normalized_model_id = str(model_id or "").strip()
        if not normalized_model_id:
            return None
        now = local_now_iso()
        prompt_placeholders = ",".join("?" for _ in DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT r.*
                FROM benchmark_records r
                JOIN benchmark_model_results m ON m.record_id = r.record_id
                WHERE m.model_id = ? AND m.status = 'pending'
                  AND r.prompt_id IN ({prompt_placeholders})
                ORDER BY r.created_at ASC
                LIMIT 1
                """,
                (normalized_model_id, *DEFAULT_LOCAL_LLM_BENCHMARK_PROMPT_IDS),
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                """
                UPDATE benchmark_model_results
                SET status = 'running', started_at = ?, updated_at = ?, error = NULL
                WHERE record_id = ? AND model_id = ? AND status = 'pending'
                """,
                (now, now, row["record_id"], normalized_model_id),
            ).rowcount
            if updated != 1:
                return None
        return self._record_row_payload(row)

    def record_model_result(
        self,
        *,
        record_id: str,
        model_id: str,
        response: UnifiedExecutionResponse,
        vram_used_mib: float | None = None,
        vram_delta_mib: float | None = None,
        gpu_util_percent: float | None = None,
        load_seconds: float | None = None,
    ) -> None:
        now = local_now_iso()
        output_summary = parse_structured_output_summary(response.output_text)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE benchmark_model_results
                SET status = 'completed',
                    completed_at = ?,
                    updated_at = ?,
                    latency_ms = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?,
                    output_text = ?,
                    label = ?,
                    confidence = ?,
                    reasoning = ?,
                    error = NULL,
                    vram_used_mib = COALESCE(?, vram_used_mib),
                    vram_delta_mib = COALESCE(?, vram_delta_mib),
                    gpu_util_percent = COALESCE(?, gpu_util_percent),
                    load_seconds = COALESCE(?, load_seconds)
                WHERE record_id = ? AND model_id = ?
                """,
                (
                    now,
                    now,
                    float(response.latency_ms or 0.0),
                    max(int(response.usage.prompt_tokens or 0), 0),
                    max(int(response.usage.completion_tokens or 0), 0),
                    max(int(response.usage.total_tokens or 0), 0),
                    response.output_text,
                    output_summary["label"],
                    output_summary["confidence"],
                    output_summary["reasoning"],
                    vram_used_mib,
                    vram_delta_mib,
                    gpu_util_percent,
                    load_seconds,
                    str(record_id or "").strip(),
                    str(model_id or "").strip(),
                ),
            )

    def record_model_failure(self, *, record_id: str, model_id: str, error: str) -> None:
        now = local_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE benchmark_model_results
                SET status = 'failed', completed_at = ?, updated_at = ?, error = ?
                WHERE record_id = ? AND model_id = ?
                """,
                (
                    now,
                    now,
                    str(error or "").strip()[:1000] or "local_benchmark_failed",
                    str(record_id or "").strip(),
                    str(model_id or "").strip(),
                ),
            )

    @staticmethod
    def _request_input_text(request_payload: dict) -> str:
        prompt = str(request_payload.get("prompt") or "").strip()
        if prompt:
            return prompt
        messages = request_payload.get("messages")
        if isinstance(messages, list):
            parts = [
                str(item.get("content") or "").strip()
                for item in messages
                if isinstance(item, dict) and str(item.get("content") or "").strip()
            ]
            return "\n".join(parts)
        return ""

    @staticmethod
    def _result_row_payload(row: sqlite3.Row) -> dict:
        return {
            "model_id": row["model_id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "latency_ms": row["latency_ms"],
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "output_text": row["output_text"],
            "label": row["label"],
            "confidence": row["confidence"],
            "reasoning": row["reasoning"],
            "error": row["error"],
            "vram_used_mib": row["vram_used_mib"],
            "vram_delta_mib": row["vram_delta_mib"],
            "gpu_util_percent": row["gpu_util_percent"],
            "load_seconds": row["load_seconds"],
        }

    @staticmethod
    def _record_row_payload(row: sqlite3.Row) -> dict:
        return {
            "record_id": str(row["record_id"]),
            "created_at": row["created_at"],
            "task_family": row["task_family"],
            "prompt_id": row["prompt_id"],
            "prompt_version": row["prompt_version"],
            "trace_id": row["trace_id"],
            "request_payload": _json_loads(row["request_payload_json"], {}),
            "openai": {
                "provider_id": row["source_provider"],
                "model_id": row["source_model"],
                "output_text": row["source_output_text"],
                "label": row["source_label"],
                "confidence": row["source_confidence"],
                "usage": _json_loads(row["source_usage_json"], {}),
                "latency_ms": row["source_latency_ms"],
                "estimated_cost": row["source_cost_usd"],
            },
        }
