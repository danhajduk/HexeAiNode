import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
from pydantic import BaseModel, Field


OPENAI_PRICING_SCHEMA_VERSION = "1.0"
OPENAI_PRICING_PARSER_VERSION = "1.0"
DEFAULT_OPENAI_PRICING_CATALOG_PATH = "data/openai_pricing_catalog.json"
DEFAULT_OPENAI_PRICING_SOURCE_URLS = [
    "https://developers.openai.com/api/docs/pricing",
    "https://openai.com/api/pricing/",
    "https://openai.com/pricing",
]
DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS = 20.0
DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT = 2
DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS = 2 * DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS
PRICE_FIELD_KEYS = (
    "input_price_per_1m",
    "cached_input_price_per_1m",
    "output_price_per_1m",
    "batch_input_price_per_1m",
    "batch_output_price_per_1m",
)
_MODEL_PREFIXES = ("gpt", "o1", "o3", "o4", "codex", "chatgpt")
_PRICE_PATTERNS = (
    re.compile(r"\$?\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*1m", re.IGNORECASE),
    re.compile(r"\$?\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*1\s*m", re.IGNORECASE),
    re.compile(r"\$?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
)
_DATE_SUFFIX_PATTERNS = (
    re.compile(r"^(?P<base>.+)-\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^(?P<base>.+)-\d{8}$"),
)
_LEGACY_SNAPSHOT_PATTERN = re.compile(r"-\d{4}$")
_BASE_ALLOW_RE = re.compile(
    r"^(?:"
    r"gpt-5(?:\.\d+)?(?:-(?:mini|nano|pro))?"
    r"|gpt-4\.1(?:-(?:mini|nano))?"
    r"|gpt-4o(?:-mini)?"
    r"|o1(?:-pro)?"
    r"|o3(?:-(?:mini|pro))?"
    r"|o4-mini"
    r")$"
)
_EXCLUDED_MODEL_TAGS = {
    "latest",
    "preview",
    "audio",
    "realtime",
    "search",
    "codex",
    "transcribe",
    "tts",
    "image",
    "moderation",
    "deep-research",
    "instruct",
    "diarize",
}
_DISPLAY_NAME_ALIASES = {
    "gpt-5": "gpt-5",
    "gpt-5 mini": "gpt-5-mini",
    "gpt-5 nano": "gpt-5-nano",
    "gpt-5 pro": "gpt-5-pro",
    "gpt-5.1": "gpt-5.1",
    "gpt-5.1 mini": "gpt-5-mini",
    "gpt-5.1 nano": "gpt-5-nano",
    "gpt-5.1 pro": "gpt-5-pro",
    "gpt-5.2": "gpt-5.2",
    "gpt-5.2 pro": "gpt-5.2-pro",
    "gpt-5 chat latest": "gpt-5-chat-latest",
    "gpt-5.1 chat latest": "gpt-5.1-chat-latest",
    "gpt-5.2 chat latest": "gpt-5.2-chat-latest",
    "gpt-5 codex": "gpt-5-codex",
    "gpt-5.1 codex": "gpt-5.1-codex",
    "gpt-5.1 codex max": "gpt-5.1-codex-max",
    "gpt-5.2 codex": "gpt-5.2-codex",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1 mini": "gpt-4.1-mini",
    "gpt-4.1 nano": "gpt-4.1-nano",
    "gpt-4o": "gpt-4o",
    "gpt-4o mini": "gpt-4o-mini",
    "gpt realtime": "gpt-realtime",
    "gpt realtime mini": "gpt-realtime-mini",
    "o3-pro": "o3-pro",
    "o3 pro": "o3-pro",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


def _normalize_optional_string(value: object) -> str | None:
    normalized = _normalize_string(value)
    return normalized or None


def _normalize_url_list(raw_value: object) -> list[str]:
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = str(raw_value or "").split(",")
    urls = []
    for value in values:
        normalized = _normalize_string(value)
        if (
            normalized.startswith("https://openai.com/")
            or normalized.startswith("https://platform.openai.com/")
            or normalized.startswith("https://developers.openai.com/")
        ):
            urls.append(normalized)
    return urls


def get_configured_openai_pricing_source_urls() -> list[str]:
    configured = _normalize_url_list(os.environ.get("SYNTHIA_OPENAI_PRICING_SOURCE_URLS"))
    return configured or list(DEFAULT_OPENAI_PRICING_SOURCE_URLS)


class OpenAIPricingEntry(BaseModel):
    model_id: str
    display_name: str
    input_price_per_1m: float | None = None
    cached_input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None
    batch_input_price_per_1m: float | None = None
    batch_output_price_per_1m: float | None = None
    source_url: str
    scraped_at: str
    pricing_status: str = "ok"
    notes: list[str] = Field(default_factory=list)


class OpenAIPricingSnapshot(BaseModel):
    schema_version: str = OPENAI_PRICING_SCHEMA_VERSION
    parser_version: str = OPENAI_PRICING_PARSER_VERSION
    source_urls: list[str] = Field(default_factory=list)
    source_url_used: str | None = None
    scraped_at: str | None = None
    refresh_state: str = "never"
    stale: bool = False
    last_error: str | None = None
    entries: list[OpenAIPricingEntry] = Field(default_factory=list)
    unknown_models: list[str] = Field(default_factory=list)
    changes: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def normalize_openai_display_name(value: str) -> str:
    normalized = _normalize_string(value).lower()
    normalized = normalized.replace("(", " ").replace(")", " ").replace("/", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    alias = _DISPLAY_NAME_ALIASES.get(normalized)
    if alias:
        return alias
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9.-]+", "-", normalized).strip("-")
    return normalized


def resolve_openai_base_model_id(model_id: str) -> str:
    normalized = _normalize_string(model_id).lower()
    if not normalized:
        return ""
    for pattern in _DATE_SUFFIX_PATTERNS:
        match = pattern.match(normalized)
        if match:
            return resolve_openai_base_model_id(match.group("base"))
    for suffix in ("-latest", "-preview"):
        if normalized.endswith(suffix):
            maybe_base = normalized[: -len(suffix)]
            if maybe_base:
                return maybe_base
    return normalized


def is_openai_date_versioned_model_id(model_id: str) -> bool:
    normalized = _normalize_string(model_id).lower()
    if not normalized:
        return False
    return any(pattern.match(normalized) is not None for pattern in _DATE_SUFFIX_PATTERNS) or bool(
        _LEGACY_SNAPSHOT_PATTERN.search(normalized)
    )


def is_regular_openai_model_id(model_id: str) -> bool:
    normalized = _normalize_string(model_id).lower()
    if not normalized:
        return False
    if is_openai_date_versioned_model_id(normalized):
        return False
    if any(tag in normalized for tag in _EXCLUDED_MODEL_TAGS):
        return False
    return _BASE_ALLOW_RE.fullmatch(normalized) is not None


def _price_fields_present(entry: OpenAIPricingEntry) -> bool:
    return any(getattr(entry, key) is not None for key in PRICE_FIELD_KEYS)


def validate_openai_pricing_entries(entries: list[OpenAIPricingEntry]) -> tuple[bool, str | None]:
    if not entries:
        return False, "pricing_entries_empty"
    for entry in entries:
        if not _normalize_string(entry.model_id):
            return False, "pricing_entry_model_id_missing"
        if not _price_fields_present(entry):
            return False, f"pricing_entry_missing_prices:{entry.model_id}"
        for key in PRICE_FIELD_KEYS:
            value = getattr(entry, key)
            if value is None:
                continue
            if value < 0:
                return False, f"pricing_entry_negative_value:{entry.model_id}:{key}"
    return True, None


class _PricingHTMLBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._buffer: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if tag in {"section", "article", "div", "p", "li", "h1", "h2", "h3", "h4", "td", "th", "span", "strong"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in {"section", "article", "div", "p", "li", "h1", "h2", "h3", "h4", "td", "th", "span", "strong"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _normalize_string(data)
        if text:
            self._buffer.append(text)

    def _flush(self) -> None:
        if not self._buffer:
            return
        text = re.sub(r"\s+", " ", " ".join(self._buffer)).strip()
        if text:
            self.blocks.append(text)
        self._buffer = []


def _parse_price_value(text: str) -> float | None:
    normalized = _normalize_string(text).lower().replace(",", "")
    for pattern in _PRICE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _classify_price_field(text: str) -> str | None:
    normalized = _normalize_string(text).lower()
    if "cached input" in normalized:
        return "cached_input_price_per_1m"
    if "batch input" in normalized:
        return "batch_input_price_per_1m"
    if "batch output" in normalized:
        return "batch_output_price_per_1m"
    if "input" in normalized:
        return "input_price_per_1m"
    if "output" in normalized:
        return "output_price_per_1m"
    return None


def _looks_like_model_heading(text: str) -> bool:
    normalized = normalize_openai_display_name(text)
    if "$" in text or not normalized:
        return False
    return normalized.startswith(_MODEL_PREFIXES)


def _parse_compact_price_tokens(text: str) -> list[float]:
    normalized = _normalize_string(text).replace(",", "")
    return [float(match) for match in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", normalized)]


def _parse_docs_pricing_row(*, block: str, source_url: str, scraped_at: str, pricing_mode: str | None) -> OpenAIPricingEntry | None:
    normalized = _normalize_string(block).replace(" ", "")
    if not normalized or "$" not in normalized:
        return None
    model_match = re.match(r"^([a-z0-9][a-z0-9.-]*)", normalized.lower())
    if model_match is None:
        return None
    model_id = model_match.group(1)
    if not is_regular_openai_model_id(model_id):
        return None
    prices = _parse_compact_price_tokens(normalized)
    if not prices:
        return None
    payload = {
        "model_id": model_id,
        "display_name": model_id,
        "source_url": source_url,
        "scraped_at": scraped_at,
        "pricing_status": "ok",
        "notes": ["docs_compact_table"],
    }
    if pricing_mode == "batch":
        payload["batch_input_price_per_1m"] = prices[0]
        if len(prices) >= 3:
            payload["batch_output_price_per_1m"] = prices[2]
        elif len(prices) >= 2:
            payload["batch_output_price_per_1m"] = prices[1]
    else:
        payload["input_price_per_1m"] = prices[0]
        if len(prices) >= 2:
            payload["cached_input_price_per_1m"] = prices[1]
        if len(prices) >= 3:
            payload["output_price_per_1m"] = prices[2]
        elif len(prices) >= 2:
            payload["output_price_per_1m"] = prices[1]
    entry = OpenAIPricingEntry.model_validate(payload)
    return entry if _price_fields_present(entry) else None


class OpenAIPricingPageParser:
    def parse(self, *, html: str, source_url: str, scraped_at: str | None = None) -> list[OpenAIPricingEntry]:
        parser = _PricingHTMLBlockParser()
        parser.feed(html)
        parser.close()
        blocks = parser.blocks
        now = scraped_at or _iso_now()
        entries: dict[str, dict] = {}
        current_model_id = None
        current_display_name = None
        pricing_mode = None
        for index, block in enumerate(blocks):
            normalized_block = _normalize_string(block).lower()
            if normalized_block in {"standard", "batch"}:
                pricing_mode = normalized_block
                continue
            docs_row = _parse_docs_pricing_row(
                block=block,
                source_url=source_url,
                scraped_at=now,
                pricing_mode=pricing_mode,
            )
            if docs_row is not None:
                existing = entries.get(docs_row.model_id)
                if existing is None:
                    entries[docs_row.model_id] = docs_row.model_dump()
                else:
                    merged = OpenAIPricingEntry.model_validate(existing).model_copy(
                        update={
                            "input_price_per_1m": docs_row.input_price_per_1m
                            if docs_row.input_price_per_1m is not None
                            else existing.get("input_price_per_1m"),
                            "cached_input_price_per_1m": docs_row.cached_input_price_per_1m
                            if docs_row.cached_input_price_per_1m is not None
                            else existing.get("cached_input_price_per_1m"),
                            "output_price_per_1m": docs_row.output_price_per_1m
                            if docs_row.output_price_per_1m is not None
                            else existing.get("output_price_per_1m"),
                            "batch_input_price_per_1m": docs_row.batch_input_price_per_1m
                            if docs_row.batch_input_price_per_1m is not None
                            else existing.get("batch_input_price_per_1m"),
                            "batch_output_price_per_1m": docs_row.batch_output_price_per_1m
                            if docs_row.batch_output_price_per_1m is not None
                            else existing.get("batch_output_price_per_1m"),
                            "notes": sorted(set(list(existing.get("notes") or []) + list(docs_row.notes))),
                        }
                    )
                    entries[docs_row.model_id] = merged.model_dump()
                continue
            if _looks_like_model_heading(block):
                current_display_name = block
                current_model_id = normalize_openai_display_name(block)
                entries.setdefault(
                    current_model_id,
                    {
                        "model_id": current_model_id,
                        "display_name": current_display_name,
                        "source_url": source_url,
                        "scraped_at": now,
                        "pricing_status": "ok",
                        "notes": [],
                    },
                )
                continue
            if current_model_id is None:
                continue
            field_key = _classify_price_field(block)
            if field_key is None:
                continue
            price_value = _parse_price_value(block)
            if price_value is None and index + 1 < len(blocks):
                price_value = _parse_price_value(blocks[index + 1])
            if price_value is None:
                entries[current_model_id]["notes"].append(f"missing_{field_key}")
                continue
            entries[current_model_id][field_key] = price_value
        parsed = []
        for payload in entries.values():
            entry = OpenAIPricingEntry.model_validate(payload)
            if _price_fields_present(entry):
                parsed.append(entry)
        return parsed


class OpenAIPricingHTMLFetcher:
    def __init__(self, *, timeout_seconds: float = DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS, retry_count: int = DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT) -> None:
        self._timeout_seconds = max(float(timeout_seconds), 1.0)
        self._retry_count = max(int(retry_count), 0)

    async def fetch_first_available(self, *, urls: list[str]) -> tuple[str, str]:
        if not urls:
            raise ValueError("openai_pricing_source_urls_empty")
        errors = []
        headers = {
            "User-Agent": "SynthiaAiNode/0.1 (+https://openai.com/)",
            "Accept": "text/html,application/xhtml+xml",
        }
        for url in urls:
            for _attempt in range(self._retry_count + 1):
                try:
                    async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                        response = await client.get(url, headers=headers)
                    if response.status_code >= 400:
                        raise RuntimeError(f"http_{response.status_code}")
                    return url, response.text
                except Exception as exc:
                    errors.append(f"{url}:{str(exc).strip() or type(exc).__name__}")
        raise RuntimeError("; ".join(errors[-3:]) or "openai_pricing_fetch_failed")


class OpenAIPricingCatalogStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def load(self) -> OpenAIPricingSnapshot | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return OpenAIPricingSnapshot.model_validate(payload)
        except Exception:
            return None

    def save(self, snapshot: OpenAIPricingSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[openai-pricing-cache-saved] %s", {"path": str(self._path), "entries": len(snapshot.entries)})


def _build_change_summary(previous: OpenAIPricingSnapshot | None, current_entries: list[OpenAIPricingEntry]) -> list[dict]:
    previous_map = {}
    if isinstance(previous, OpenAIPricingSnapshot):
        previous_map = {entry.model_id: entry for entry in previous.entries}
    changes = []
    for entry in current_entries:
        previous_entry = previous_map.get(entry.model_id)
        if previous_entry is None:
            changes.append({"model_id": entry.model_id, "change": "new"})
            continue
        for key in PRICE_FIELD_KEYS:
            old_value = getattr(previous_entry, key)
            new_value = getattr(entry, key)
            if old_value != new_value:
                changes.append({"model_id": entry.model_id, "field": key, "old": old_value, "new": new_value})
    return changes


class OpenAIPricingCatalogService:
    def __init__(
        self,
        *,
        logger,
        catalog_path: str = DEFAULT_OPENAI_PRICING_CATALOG_PATH,
        source_urls: list[str] | None = None,
        refresh_interval_seconds: int = DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS,
        stale_tolerance_seconds: int = DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS,
        fetcher=None,
        parser=None,
        store=None,
    ) -> None:
        self._logger = logger
        self._source_urls = source_urls or get_configured_openai_pricing_source_urls()
        self._refresh_interval_seconds = int(refresh_interval_seconds)
        self._stale_tolerance_seconds = int(stale_tolerance_seconds)
        self._fetcher = fetcher or OpenAIPricingHTMLFetcher(
            timeout_seconds=float(os.environ.get("SYNTHIA_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS") or DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS),
            retry_count=int(os.environ.get("SYNTHIA_OPENAI_PRICING_FETCH_RETRY_COUNT") or DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT),
        )
        self._parser = parser or OpenAIPricingPageParser()
        self._store = store or OpenAIPricingCatalogStore(path=catalog_path, logger=logger)

    def load_snapshot(self) -> OpenAIPricingSnapshot | None:
        return self._store.load() if self._store is not None and hasattr(self._store, "load") else None

    def should_refresh(self, snapshot: OpenAIPricingSnapshot | None) -> bool:
        if self._refresh_interval_seconds <= 0:
            return False
        if snapshot is None or not snapshot.scraped_at:
            return True
        try:
            scraped_at = datetime.fromisoformat(snapshot.scraped_at.replace("Z", "+00:00"))
        except Exception:
            return True
        return (datetime.now(timezone.utc) - scraped_at).total_seconds() >= self._refresh_interval_seconds

    def is_stale(self, snapshot: OpenAIPricingSnapshot | None) -> bool:
        if snapshot is None or snapshot.stale:
            return True
        if not snapshot.scraped_at:
            return True
        try:
            scraped_at = datetime.fromisoformat(snapshot.scraped_at.replace("Z", "+00:00"))
        except Exception:
            return True
        if self._stale_tolerance_seconds <= 0:
            return False
        return (datetime.now(timezone.utc) - scraped_at).total_seconds() >= self._stale_tolerance_seconds

    async def refresh(self, *, force: bool = False) -> dict:
        previous = self.load_snapshot()
        notes = ["live_pricing_scrape_disabled"]
        if hasattr(self._logger, "info"):
            self._logger.info("[openai-pricing-refresh-skipped] %s", {"force": force, "manual_only": True})
        if previous is None:
            return {
                "status": "manual_only",
                "changed": False,
                "snapshot": None,
                "notes": notes,
            }
        snapshot = previous.model_copy(
            update={
                "refresh_state": "manual",
                "stale": False,
                "last_error": None,
                "notes": sorted(set(list(previous.notes or []) + notes)),
            }
        )
        self._store.save(snapshot)
        return {
            "status": "manual_only",
            "changed": False,
            "snapshot": snapshot.model_dump(),
            "notes": notes,
        }

    def save_manual_pricing(
        self,
        *,
        model_id: str,
        display_name: str | None = None,
        input_price_per_1m: float | None = None,
        output_price_per_1m: float | None = None,
    ) -> dict:
        normalized_model_id = resolve_openai_base_model_id(model_id)
        if not normalized_model_id:
            raise ValueError("model_id is required")
        if input_price_per_1m is None and output_price_per_1m is None:
            raise ValueError("at least one manual price is required")
        previous = self.load_snapshot()
        entries = list(previous.entries) if previous is not None else []
        existing_index = next((index for index, entry in enumerate(entries) if entry.model_id == normalized_model_id), None)
        manual_entry = OpenAIPricingEntry(
            model_id=normalized_model_id,
            display_name=_normalize_string(display_name) or normalized_model_id,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
            cached_input_price_per_1m=(entries[existing_index].cached_input_price_per_1m if existing_index is not None else None),
            batch_input_price_per_1m=(entries[existing_index].batch_input_price_per_1m if existing_index is not None else None),
            batch_output_price_per_1m=(entries[existing_index].batch_output_price_per_1m if existing_index is not None else None),
            source_url="manual://local_override",
            scraped_at=_iso_now(),
            pricing_status="manual",
            notes=["manual_pricing_override"],
        )
        if existing_index is not None:
            existing = entries[existing_index]
            manual_entry = manual_entry.model_copy(
                update={
                    "display_name": _normalize_string(display_name) or existing.display_name,
                    "input_price_per_1m": input_price_per_1m if input_price_per_1m is not None else existing.input_price_per_1m,
                    "output_price_per_1m": output_price_per_1m if output_price_per_1m is not None else existing.output_price_per_1m,
                    "cached_input_price_per_1m": existing.cached_input_price_per_1m,
                    "batch_input_price_per_1m": existing.batch_input_price_per_1m,
                    "batch_output_price_per_1m": existing.batch_output_price_per_1m,
                }
            )
            entries[existing_index] = manual_entry
        else:
            entries.append(manual_entry)
        changes = _build_change_summary(previous, entries)
        snapshot = OpenAIPricingSnapshot(
            source_urls=list(self._source_urls),
            source_url_used="manual://local_override",
            scraped_at=_iso_now(),
            refresh_state="manual",
            stale=False,
            last_error=None,
            entries=entries,
            unknown_models=(previous.unknown_models if previous is not None else []),
            changes=changes,
            notes=["manual_pricing_saved"],
        )
        self._store.save(snapshot)
        return {"status": "manual_saved", "changed": True, "snapshot": snapshot.model_dump(), "model_id": normalized_model_id}

    def get_pricing_entry(self, model_id: str) -> OpenAIPricingEntry | None:
        snapshot = self.load_snapshot()
        if snapshot is None:
            return None
        target = resolve_openai_base_model_id(model_id)
        for candidate in (_normalize_string(model_id).lower(), target):
            if not candidate:
                continue
            for entry in snapshot.entries:
                if entry.model_id == candidate:
                    if self.is_stale(snapshot):
                        return entry.model_copy(update={"pricing_status": "stale"})
                    return entry
        return None

    def merge_model_capabilities(self, models: list) -> tuple[list, list[str]]:
        snapshot = self.load_snapshot()
        stale = self.is_stale(snapshot)
        unknown_models: list[str] = []
        merged = []
        for model in models:
            pricing_entry = self.get_pricing_entry(getattr(model, "model_id", ""))
            if pricing_entry is None:
                unknown_models.append(getattr(model, "model_id", ""))
                merged.append(
                    model.model_copy(
                        update={
                            "base_model_id": resolve_openai_base_model_id(getattr(model, "model_id", "")),
                            "pricing_status": "scrape_failed" if snapshot is None else "unknown",
                            "pricing_notes": ["pricing_not_found"],
                        }
                    )
                )
                continue
            merged.append(
                model.model_copy(
                    update={
                        "base_model_id": pricing_entry.model_id,
                        "pricing_input": pricing_entry.input_price_per_1m,
                        "pricing_output": pricing_entry.output_price_per_1m,
                        "cached_pricing_input": pricing_entry.cached_input_price_per_1m,
                        "batch_pricing_input": pricing_entry.batch_input_price_per_1m,
                        "batch_pricing_output": pricing_entry.batch_output_price_per_1m,
                        "pricing_status": "stale" if stale else pricing_entry.pricing_status,
                        "pricing_source_url": pricing_entry.source_url,
                        "pricing_scraped_at": pricing_entry.scraped_at,
                        "pricing_notes": list(pricing_entry.notes),
                    }
                )
            )
        if snapshot is not None and unknown_models != snapshot.unknown_models:
            updated = snapshot.model_copy(update={"unknown_models": sorted(set(unknown_models))})
            self._store.save(updated)
        return merged, sorted(set(unknown_models))

    def diagnostics_payload(self) -> dict:
        snapshot = self.load_snapshot()
        if snapshot is None:
            return {
                "configured": True,
                "refresh_state": "missing",
                "stale": True,
                "entry_count": 0,
                "source_urls": list(self._source_urls),
                "source_url_used": None,
                "last_refresh_time": None,
                "unknown_models": [],
                "last_error": None,
                "notes": ["live_pricing_scrape_disabled"],
            }
        return {
            "configured": True,
            "refresh_state": snapshot.refresh_state,
            "stale": self.is_stale(snapshot),
            "entry_count": len(snapshot.entries),
            "source_urls": snapshot.source_urls,
            "source_url_used": snapshot.source_url_used,
            "last_refresh_time": snapshot.scraped_at,
            "unknown_models": snapshot.unknown_models,
            "last_error": snapshot.last_error,
            "changes": snapshot.changes,
            "notes": snapshot.notes,
        }


def get_openai_model_pricing(model_id: str, *, pricing_service: OpenAIPricingCatalogService | None = None) -> dict | None:
    service = pricing_service or OpenAIPricingCatalogService(
        logger=_NullLogger(),
        catalog_path=os.environ.get("SYNTHIA_OPENAI_PRICING_CATALOG_PATH", DEFAULT_OPENAI_PRICING_CATALOG_PATH),
        refresh_interval_seconds=int(
            os.environ.get(
                "SYNTHIA_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS",
                str(DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS),
            )
        ),
        stale_tolerance_seconds=int(
            os.environ.get(
                "SYNTHIA_OPENAI_PRICING_STALE_TOLERANCE_SECONDS",
                str(DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS),
            )
        ),
    )
    entry = service.get_pricing_entry(model_id)
    if entry is None:
        return None
    return {
        "currency": "usd",
        "input_per_1m_tokens": entry.input_price_per_1m,
        "cached_input_per_1m_tokens": entry.cached_input_price_per_1m,
        "output_per_1m_tokens": entry.output_price_per_1m,
        "batch_input_per_1m_tokens": entry.batch_input_price_per_1m,
        "batch_output_per_1m_tokens": entry.batch_output_price_per_1m,
        "pricing_status": entry.pricing_status,
        "source_url": entry.source_url,
        "scraped_at": entry.scraped_at,
        "notes": list(entry.notes),
    }


class _NullLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None
