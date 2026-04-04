import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from pydantic import BaseModel, Field


OPENAI_PRICING_SCHEMA_VERSION = "2.0"
OPENAI_PRICING_PARSER_VERSION = "2.0"
DEFAULT_OPENAI_PRICING_CATALOG_PATH = "providers/openai/provider_model_pricing.json"
DEFAULT_OPENAI_PRICING_OVERRIDES_PATH = "providers/openai/provider_model_pricing_overrides.json"
DEFAULT_OPENAI_PRICING_MANUAL_CONFIG_PATH = "config/openai-pricing.yaml"
DEFAULT_OPENAI_PRICING_TEXT_CACHE_PATH = "providers/openai/pricing_page_text_cache.json"
DEFAULT_OPENAI_PRICING_NORMALIZED_TEXT_CACHE_PATH = "providers/openai/pricing_page_text_normalized_cache.json"
DEFAULT_OPENAI_PRICING_SECTIONS_CACHE_PATH = "providers/openai/pricing_page_sections_cache.json"
DEFAULT_OPENAI_PRICING_DEBUG_RESPONSE_PATH = "data/response.json"
DEFAULT_OPENAI_PRICING_PROMPT_SENT_PATH = "data/promtp_sent.txt"
DEFAULT_OPENAI_PRICING_EXTRACTION_PROMPT_PATH = "prompts/openai_model_capability_classification_prompt.txt"
DEFAULT_OPENAI_PRICING_SOURCE_URLS = [
    "https://developers.openai.com/api/docs/pricing",
]
DEFAULT_OPENAI_PRICING_MARKDOWN_URL = "https://developers.openai.com/api/docs/pricing.md"
DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS = 20.0
DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT = 2
DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS = 2 * DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS
_CANONICAL_PRICING_BASIS = {
    "per_1m_tokens",
    "per_1m_characters",
    "per_image",
    "per_second",
    "per_minute",
}
_CANONICAL_FAMILIES = {
    "llm",
    "embeddings",
    "realtime_voice",
    "text_to_speech",
    "speech_to_text",
    "image_generation",
    "video_generation",
    "moderation",
}
_MODEL_PREFIXES = ("gpt", "o1", "o3", "o4", "codex", "chatgpt", "whisper", "tts", "sora", "text-embedding", "omni")
_PRICING_SECTION_KEYS = [
    "text_tokens",
    "image_tokens",
    "audio_tokens",
    "video",
    "transcription_and_speech_generation",
    "other_models",
    "image_generation",
    "embeddings",
    "moderation",
]
_PRICING_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "text_tokens": ("text tokens", "text token", "tokens", "language models", "text"),
    "image_tokens": ("image tokens", "vision tokens"),
    "audio_tokens": ("audio tokens", "realtime audio", "realtime"),
    "video": ("video", "video models"),
    "transcription_and_speech_generation": (
        "transcription and speech generation",
        "transcription & speech generation",
        "speech generation",
        "speech and transcription",
    ),
    "other_models": ("other models",),
    "image_generation": ("image generation", "images"),
    "embeddings": ("embeddings", "embedding"),
    "moderation": ("moderation", "moderation models"),
}
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
    r"|gpt-image-[a-z0-9.-]+(?:-mini)?"
    r"|gpt-realtime-[a-z0-9.-]+"
    r"|whisper-[a-z0-9.-]+"
    r"|tts(?:-hd)?-[a-z0-9.-]+"
    r"|text-embedding-[a-z0-9.-]+"
    r"|omni-moderation-[a-z0-9.-]+"
    r"|sora-[a-z0-9.-]+"
    r")$"
)
_EXCLUDED_MODEL_TAGS = {
    "latest",
    "preview",
    "search",
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
    "gpt-5.2 mini": "gpt-5.2-mini",
    "gpt-5.2 nano": "gpt-5.2-nano",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1 mini": "gpt-4.1-mini",
    "gpt-4.1 nano": "gpt-4.1-nano",
    "gpt-4o": "gpt-4o",
    "gpt-4o mini": "gpt-4o-mini",
    "gpt realtime mini": "gpt-realtime-mini",
    "gpt image 1": "gpt-image-1",
}
_OPENAI_MANUAL_RATE_FALLBACKS = {
    "gpt-5.4": {"input_price": 2.50, "cached_input_price": 0.25, "output_price": 15.00},
    "gpt-5.4-2026-03-05": {"input_price": 2.50, "cached_input_price": 0.25, "output_price": 15.00},
    "gpt-5.4-mini": {"input_price": 0.75, "cached_input_price": 0.075, "output_price": 4.50},
    "gpt-5.4-mini-2026-03-17": {"input_price": 0.75, "cached_input_price": 0.075, "output_price": 4.50},
    "gpt-5.4-nano": {"input_price": 0.20, "cached_input_price": 0.02, "output_price": 1.25},
    "gpt-5.4-nano-2026-03-17": {"input_price": 0.20, "cached_input_price": 0.02, "output_price": 1.25},
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


def _is_ai_extraction_target_model_id(model_id: str) -> bool:
    normalized = _normalize_string(model_id).lower()
    if not normalized:
        return False
    if is_openai_date_versioned_model_id(normalized) and not normalized.startswith("omni-moderation-"):
        return False
    if "latest" in normalized or "preview" in normalized:
        return False
    return True


def _normalize_family(value: object, *, model_id: str) -> str:
    raw = _normalize_string(value).lower()
    if raw == "realtime":
        raw = "realtime_voice"
    if raw in _CANONICAL_FAMILIES:
        return raw
    derived = _classify_family_from_model_id(model_id)
    if derived in _CANONICAL_FAMILIES:
        return str(derived)
    return "llm"


def _classify_family_from_model_id(model_id: str) -> str | None:
    normalized = _normalize_string(model_id).lower()
    if normalized.startswith("gpt-image-"):
        return "image_generation"
    if normalized.startswith("sora-"):
        return "video_generation"
    if normalized.startswith("gpt-realtime-"):
        return "realtime_voice"
    if normalized.startswith("whisper-"):
        return "speech_to_text"
    if normalized.startswith("tts-") or normalized.startswith("tts-hd-"):
        return "text_to_speech"
    if normalized.startswith("text-embedding-"):
        return "embeddings"
    if normalized.startswith("omni-moderation-"):
        return "moderation"
    if normalized.startswith("gpt-"):
        return "llm"
    return None


def _default_pricing_basis_for_family(family: str) -> str:
    if family in {"llm", "embeddings", "realtime_voice", "moderation"}:
        return "per_1m_tokens"
    if family == "text_to_speech":
        return "per_1m_characters"
    if family == "speech_to_text":
        return "per_minute"
    if family == "image_generation":
        return "per_image"
    if family == "video_generation":
        return "per_second"
    return "per_1m_tokens"


def _default_normalized_unit(basis: str) -> str:
    if basis == "per_1m_tokens":
        return "per_1m_tokens"
    if basis == "per_1m_characters":
        return "per_1m_characters"
    if basis == "per_image":
        return "medium_1024x1536_per_image"
    if basis == "per_second":
        return "per_second"
    if basis == "per_minute":
        return "per_minute"
    return "unknown"


def _normalize_price(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    else:
        text = _normalize_string(value)
        if not text:
            return None
        text = text.replace("$", "").replace(",", "")
        try:
            parsed = float(text)
        except ValueError:
            return None
    if parsed < 0:
        return None
    return parsed


def _compute_normalized_price(*, basis: str, input_price: float | None, output_price: float | None, normalized_price: float | None) -> float | None:
    if normalized_price is not None:
        return normalized_price
    if basis == "per_1m_tokens":
        return output_price if output_price is not None else input_price
    if basis in {"per_1m_characters", "per_image", "per_second", "per_minute"}:
        return output_price if output_price is not None else input_price
    return output_price if output_price is not None else input_price


def _sanitize_non_applicable_price_fields(
    *,
    basis: str,
    input_price: float | None,
    cached_input_price: float | None,
    output_price: float | None,
) -> tuple[float | None, float | None, float | None]:
    if basis != "per_1m_tokens":
        cached_input_price = None
        if input_price == 0.0:
            input_price = None
        if output_price == 0.0:
            output_price = None
    return input_price, cached_input_price, output_price


def _enforce_family_pricing_rules(
    *,
    family: str,
    basis: str,
    input_price: float | None,
    cached_input_price: float | None,
    output_price: float | None,
    normalized_price: float | None,
    normalized_unit: str,
    notes: list[str],
) -> tuple[str, float | None, float | None, float | None, float | None, str, list[str]]:
    normalized_notes = sorted(set(note for note in notes if _normalize_string(note)))
    if family in {"llm", "embeddings", "realtime_voice"}:
        basis = "per_1m_tokens"
        normalized_unit = "per_1m_tokens"
        normalized_price = _compute_normalized_price(
            basis=basis,
            input_price=input_price,
            output_price=output_price,
            normalized_price=normalized_price,
        )
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    if family == "speech_to_text":
        basis = "per_minute"
        normalized_unit = "per_minute"
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = normalized_price if normalized_price is not None else (output_price if output_price is not None else input_price)
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    if family == "text_to_speech":
        if basis not in {"per_1m_characters", "per_minute"}:
            basis = "per_1m_characters"
        normalized_unit = "per_1m_characters" if basis == "per_1m_characters" else "per_minute"
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = normalized_price if normalized_price is not None else (output_price if output_price is not None else input_price)
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    if family == "image_generation":
        basis = "per_image"
        normalized_unit = "medium_1024x1536_per_image"
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = normalized_price if normalized_price is not None else (output_price if output_price is not None else input_price)
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    if family == "video_generation":
        basis = "per_second"
        normalized_unit = "per_second"
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = normalized_price if normalized_price is not None else (output_price if output_price is not None else input_price)
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    if family == "moderation":
        basis = "per_1m_tokens"
        normalized_unit = "per_1m_tokens"
        free_note = any("free of charge" in note.lower() or note.lower() == "free" for note in normalized_notes)
        if free_note and normalized_price is None and output_price is None and input_price is None:
            normalized_price = 0.0
            normalized_notes = sorted(set(normalized_notes + ["status:free"]))
        elif free_note:
            normalized_notes = sorted(set(normalized_notes + ["status:free"]))
        else:
            normalized_notes = sorted(set(normalized_notes + ["status:priced"]))
        normalized_price = _compute_normalized_price(
            basis=basis,
            input_price=input_price,
            output_price=output_price,
            normalized_price=normalized_price,
        )
        return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes
    return basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes


class OpenAIPricingEntry(BaseModel):
    model_id: str
    family: str
    pricing_basis: str
    input_price: float | None = None
    cached_input_price: float | None = None
    output_price: float | None = None
    normalized_price: float | None = None
    normalized_unit: str
    notes: list[str] = Field(default_factory=list)
    source_url: str
    extracted_at: str
    extraction_status: str = "ok"


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
    extraction_model: str | None = None
    extraction_source: str | None = None
    text_cache_path: str | None = None
    normalized_text_cache_path: str | None = None
    sections_cache_path: str | None = None


def validate_openai_pricing_entries(entries: list[OpenAIPricingEntry]) -> tuple[bool, str | None]:
    if not entries:
        return False, "pricing_entries_empty"
    for entry in entries:
        if not _normalize_string(entry.model_id):
            return False, "pricing_entry_model_id_missing"
        if entry.pricing_basis not in _CANONICAL_PRICING_BASIS:
            return False, f"pricing_entry_basis_invalid:{entry.model_id}"
        if entry.family not in _CANONICAL_FAMILIES:
            return False, f"pricing_entry_family_invalid:{entry.model_id}"
        if entry.normalized_price is not None and entry.normalized_price < 0:
            return False, f"pricing_entry_normalized_negative:{entry.model_id}"
        if not _normalize_string(entry.normalized_unit):
            return False, f"pricing_entry_normalized_unit_missing:{entry.model_id}"
        for value in (entry.input_price, entry.cached_input_price, entry.output_price):
            if value is not None and value < 0:
                return False, f"pricing_entry_negative_value:{entry.model_id}"
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


def _parse_compact_price_tokens(text: str) -> list[float]:
    normalized = _normalize_string(text).replace(",", "")
    return [float(match) for match in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", normalized)]


def _looks_like_model_heading(text: str) -> bool:
    normalized = normalize_openai_display_name(text)
    if "$" in text or not normalized:
        return False
    return normalized.startswith(_MODEL_PREFIXES)


class OpenAIPricingPageParser:
    def extract_relevant_text(self, *, html: str) -> str:
        parser = _PricingHTMLBlockParser()
        parser.feed(html)
        parser.close()
        keywords = ("pricing", "token", "image", "audio", "video", "input", "output", "$", "gpt", "whisper", "tts", "sora")
        selected = [block for block in parser.blocks if any(keyword in block.lower() for keyword in keywords)]
        if not selected:
            selected = parser.blocks
        text = "\n".join(selected)
        return text[:40000]

    def parse(self, *, html: str, source_url: str, scraped_at: str | None = None) -> list[OpenAIPricingEntry]:
        parser = _PricingHTMLBlockParser()
        parser.feed(html)
        parser.close()
        blocks = parser.blocks
        now = scraped_at or _iso_now()
        entries: dict[str, OpenAIPricingEntry] = {}
        current_model_id: str | None = None
        for block in blocks:
            if _looks_like_model_heading(block):
                current_model_id = normalize_openai_display_name(block)
            compact_match = re.match(r"^([a-z0-9][a-z0-9.-]*)\s+\$", block.lower())
            if compact_match:
                current_model_id = compact_match.group(1)
            if current_model_id is None:
                continue
            model_id = resolve_openai_base_model_id(current_model_id)
            if not is_regular_openai_model_id(model_id):
                continue
            prices = _parse_compact_price_tokens(block)
            if not prices:
                continue
            family = _normalize_family(None, model_id=model_id)
            basis = _default_pricing_basis_for_family(family)
            input_price = prices[0]
            cached_price = prices[1] if len(prices) > 2 else None
            output_price = prices[2] if len(prices) > 2 else (prices[1] if len(prices) > 1 else None)
            entry = OpenAIPricingEntry(
                model_id=model_id,
                family=family,
                pricing_basis=basis,
                input_price=input_price,
                cached_input_price=cached_price,
                output_price=output_price,
                normalized_price=_compute_normalized_price(
                    basis=basis,
                    input_price=input_price,
                    output_price=output_price,
                    normalized_price=None,
                ),
                normalized_unit=_default_normalized_unit(basis),
                notes=["deterministic_html_parse"],
                source_url=source_url,
                extracted_at=now,
                extraction_status="ok",
            )
            entries[entry.model_id] = entry
        return sorted(entries.values(), key=lambda item: item.model_id)


class OpenAIPricingHTMLFetcher:
    def __init__(self, *, timeout_seconds: float = DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS, retry_count: int = DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT) -> None:
        self._timeout_seconds = max(float(timeout_seconds), 1.0)
        self._retry_count = max(int(retry_count), 0)

    async def fetch_first_available(self, *, urls: list[str]) -> tuple[str, str]:
        if not urls:
            raise ValueError("openai_pricing_source_urls_empty")
        errors = []
        headers = {
            "User-Agent": "HexeAiNode/0.1 (+https://openai.com/)",
            "Accept": "text/markdown,text/plain,text/html,application/xhtml+xml",
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

    @property
    def path(self) -> str:
        return str(self._path)

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
        for key in (
            "pricing_basis",
            "input_price",
            "cached_input_price",
            "output_price",
            "normalized_price",
            "normalized_unit",
        ):
            old_value = getattr(previous_entry, key)
            new_value = getattr(entry, key)
            if old_value != new_value:
                changes.append({"model_id": entry.model_id, "field": key, "old": old_value, "new": new_value})
    return changes


def _strip_json_fence(value: str) -> str:
    text = _normalize_string(value)
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _select_pricing_extraction_model(model_ids: list[str]) -> str | None:
    llm_models = sorted({resolve_openai_base_model_id(model_id) for model_id in model_ids if _normalize_string(model_id)})
    llm_models = [model_id for model_id in llm_models if _normalize_family(None, model_id=model_id) == "llm"]
    if not llm_models:
        return None

    def rank(model_id: str) -> tuple[int, int, int, str]:
        normalized = _normalize_string(model_id).lower()
        if normalized.endswith("-nano"):
            return (0, 0, 0, normalized)
        if normalized.endswith("-mini"):
            return (1, 0, 0, normalized)
        if normalized.endswith("-pro"):
            return (3, 0, 0, normalized)
        major = 999
        minor = 999
        version = normalized.removeprefix("gpt-").split("-", 1)[0]
        if version:
            pieces = version.split(".", 1)
            try:
                major = int(pieces[0])
            except ValueError:
                major = 999
            if len(pieces) > 1:
                try:
                    minor = int(pieces[1])
                except ValueError:
                    minor = 999
        return (2, major, minor, normalized)

    return sorted(llm_models, key=rank)[0]


def _load_pricing_prompt_template() -> str:
    path = Path(DEFAULT_OPENAI_PRICING_EXTRACTION_PROMPT_PATH)
    if not path.exists():
        raise ValueError("pricing_prompt_template_missing")
    text = path.read_text(encoding="utf-8")
    if "{{MODEL_LIST}}" not in text or "{{PRICING_PAGE_TEXT}}" not in text:
        raise ValueError("pricing_prompt_template_placeholders_missing")
    return text


def _build_pricing_extraction_prompt(*, model_ids: list[str], page_text: str) -> tuple[str, str]:
    template = _load_pricing_prompt_template()
    model_lines = "\n".join(f"- {item}" for item in model_ids)
    prompt = template.replace("{{MODEL_LIST}}", model_lines).replace("{{PRICING_PAGE_TEXT}}", page_text)
    system_prompt = "Follow the provided user prompt exactly. Return JSON only."
    return system_prompt, prompt


def _build_family_pricing_extraction_prompt(*, prompt_name: str, model_ids: list[str], section_text: str) -> tuple[str, str]:
    family_instructions = {
        "llm_pricing_extraction_prompt": "Extract pricing only for LLM models from the provided text token section.",
        "realtime_audio_pricing_extraction_prompt": "Extract pricing only for realtime/audio models from the provided section.",
        "image_generation_pricing_extraction_prompt": "Extract pricing only for image generation models from the provided section.",
        "video_pricing_extraction_prompt": "Extract pricing only for video generation models from the provided section.",
        "stt_tts_other_pricing_extraction_prompt": "Extract pricing only for speech-to-text and text-to-speech models from the provided section.",
        "embeddings_moderation_pricing_extraction_prompt": "Extract pricing only for embeddings and moderation models from the provided section.",
    }
    base_system_prompt, base_user_prompt = _build_pricing_extraction_prompt(model_ids=model_ids, page_text=section_text)
    schema = (
        '{\n'
        '  "models": [\n'
        "    {\n"
        '      "model_id": "string",\n'
        '      "family": "llm|embeddings|realtime_voice|text_to_speech|speech_to_text|image_generation|video_generation|moderation",\n'
        '      "pricing_basis": "per_1m_tokens|per_1m_characters|per_image|per_second|per_minute",\n'
        '      "input_price": "number|null",\n'
        '      "cached_input_price": "number|null",\n'
        '      "output_price": "number|null",\n'
        '      "normalized_price": "number|null",\n'
        '      "normalized_unit": "string",\n'
        '      "notes": ["string"]\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    instruction = family_instructions.get(prompt_name, "Extract pricing only for the provided target models and section.")
    user_prompt = (
        f"Prompt Family: {prompt_name}\n"
        f"{instruction}\n\n"
        f"{base_user_prompt}\n\n"
        "Return JSON only using this schema:\n"
        f"{schema}"
    )
    return base_system_prompt, user_prompt


def _normalize_extracted_payload(*, payload: object, allowed_models: dict[str, str], source_url: str, extracted_at: str) -> list[OpenAIPricingEntry]:
    if not isinstance(payload, dict):
        raise ValueError("pricing_extraction_payload_invalid")
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise ValueError("pricing_extraction_models_missing")
    entries: list[OpenAIPricingEntry] = []
    seen: set[str] = set()
    for raw_item in raw_models:
        if not isinstance(raw_item, dict):
            raise ValueError("pricing_extraction_entry_invalid")
        raw_model_id = _normalize_string(raw_item.get("model_id")).lower()
        base_model_id = resolve_openai_base_model_id(raw_item.get("model_id") or "")
        model_id = raw_model_id if raw_model_id in allowed_models else base_model_id
        if model_id not in allowed_models:
            continue
        if model_id in seen:
            continue
        family = _normalize_family(raw_item.get("family"), model_id=model_id)
        if family != allowed_models[model_id]:
            family = allowed_models[model_id]

        basis = _normalize_string(raw_item.get("pricing_basis")).lower() or _default_pricing_basis_for_family(family)
        if basis not in _CANONICAL_PRICING_BASIS:
            raise ValueError(f"pricing_extraction_basis_invalid:{model_id}")

        input_price = _normalize_price(raw_item.get("input_price"))
        cached_input_price = _normalize_price(raw_item.get("cached_input_price"))
        output_price = _normalize_price(raw_item.get("output_price"))
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = _normalize_price(raw_item.get("normalized_price"))
        normalized_unit = _normalize_string(raw_item.get("normalized_unit")) or _default_normalized_unit(basis)
        notes = raw_item.get("notes") if isinstance(raw_item.get("notes"), list) else []
        normalized_notes = sorted({str(note).strip() for note in notes if str(note).strip()})
        if "batch_input_price" in raw_item or "batch_output_price" in raw_item:
            normalized_notes = sorted(set(normalized_notes + ["batch_prices_ignored"]))
        basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, normalized_notes = _enforce_family_pricing_rules(
            family=family,
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
            normalized_price=normalized_price,
            normalized_unit=normalized_unit,
            notes=normalized_notes,
        )

        entry = OpenAIPricingEntry(
            model_id=model_id,
            family=family,
            pricing_basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
            normalized_price=normalized_price,
            normalized_unit=normalized_unit,
            notes=normalized_notes,
            source_url=source_url,
            extracted_at=extracted_at,
            extraction_status="ok",
        )
        entries.append(entry)
        seen.add(model_id)
    entries.sort(key=lambda item: item.model_id)
    is_valid, error = validate_openai_pricing_entries(entries)
    if not is_valid:
        raise ValueError(str(error or "pricing_extraction_validation_failed"))
    return entries


def _validate_family_extracted_entries(*, family: str, entries: list[OpenAIPricingEntry]) -> tuple[bool, str | None]:
    if not entries:
        return True, None
    for entry in entries:
        if family in {"llm", "realtime_voice", "embeddings"}:
            if entry.pricing_basis != "per_1m_tokens":
                return False, f"family_validation_basis_invalid:{family}:{entry.model_id}"
            if entry.input_price is None and entry.output_price is None and entry.normalized_price is None:
                return False, f"family_validation_token_prices_missing:{family}:{entry.model_id}"
        elif family == "speech_to_text":
            if entry.pricing_basis != "per_minute":
                return False, f"family_validation_basis_invalid:{family}:{entry.model_id}"
            if entry.normalized_price is None:
                return False, f"family_validation_normalized_missing:{family}:{entry.model_id}"
        elif family == "text_to_speech":
            if entry.pricing_basis not in {"per_1m_characters", "per_minute"}:
                return False, f"family_validation_basis_invalid:{family}:{entry.model_id}"
            if entry.normalized_unit not in {"per_1m_characters", "per_minute"}:
                return False, f"family_validation_unit_invalid:{family}:{entry.model_id}"
            if entry.normalized_price is None:
                return False, f"family_validation_normalized_missing:{family}:{entry.model_id}"
        elif family == "image_generation":
            if entry.pricing_basis != "per_image":
                return False, f"family_validation_basis_invalid:{family}:{entry.model_id}"
            if entry.normalized_price is None:
                return False, f"family_validation_normalized_missing:{family}:{entry.model_id}"
        elif family == "video_generation":
            if entry.pricing_basis != "per_second":
                return False, f"family_validation_basis_invalid:{family}:{entry.model_id}"
            if entry.normalized_price is None:
                return False, f"family_validation_normalized_missing:{family}:{entry.model_id}"
        elif family == "moderation":
            status_notes = {note for note in entry.notes if note.startswith("status:")}
            if not status_notes:
                return False, f"family_validation_status_missing:{family}:{entry.model_id}"
    return True, None


def _load_pricing_overrides(*, path: str) -> dict[str, dict]:
    payload_path = Path(path)
    if not payload_path.exists():
        return {}
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {}
    overrides = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = resolve_openai_base_model_id(item.get("model_id") or "")
        if not model_id:
            continue
        overrides[model_id] = item
    return overrides


def _save_pricing_overrides(*, path: str, overrides: dict[str, dict]) -> None:
    payload_path = Path(path)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_models = []
    for model_id in sorted(overrides):
        item = overrides.get(model_id)
        if not isinstance(item, dict):
            continue
        normalized_item = dict(item)
        normalized_item["model_id"] = model_id
        normalized_models.append(normalized_item)
    payload = {"schema_version": "1.0", "models": normalized_models}
    temp_path = payload_path.with_suffix(f"{payload_path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(payload_path)


def _load_manual_pricing_yaml(*, path: str) -> dict[str, dict]:
    payload_path = Path(path)
    if not payload_path.exists():
        return {}
    overrides: dict[str, dict] = {}
    current_model_id: str | None = None
    current_fields: dict[str, float | None] = {}
    for raw_line in payload_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in {"version: 1", "models:"}:
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            if current_model_id is not None:
                overrides[current_model_id] = dict(current_fields)
            current_model_id = resolve_openai_base_model_id(stripped[:-1].strip().strip("'\""))
            current_fields = {}
            continue
        if current_model_id is None or not line.startswith("    ") or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        yaml_key = key.strip().lower()
        value_text = raw_value.strip()
        if value_text in {"", "null", "~"}:
            normalized_value = None
        else:
            normalized_value = _normalize_price(value_text)
        if yaml_key == "input":
            current_fields["input_price"] = normalized_value
        elif yaml_key == "cached input":
            current_fields["cached_input_price"] = normalized_value
        elif yaml_key == "output":
            current_fields["output_price"] = normalized_value
    if current_model_id is not None:
        overrides[current_model_id] = dict(current_fields)
    return overrides


def _save_manual_pricing_yaml(*, path: str, models: list[dict[str, object]]) -> None:
    payload_path = Path(path)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Manual OpenAI pricing overrides used by the node.",
        "# Edit the values below as needed. Use null to leave a field unset.",
        "# Units are USD per 1M tokens.",
        "version: 1",
        "models:",
    ]
    for model in models:
        model_id = _normalize_string(model.get("model_id"))
        if not model_id:
            continue
        lines.append(f"  {model_id}:")
        lines.append(f"    Input: {_yaml_scalar(model.get('input_price'))}")
        lines.append(f"    Cached input: {_yaml_scalar(model.get('cached_input_price'))}")
        lines.append(f"    Output: {_yaml_scalar(model.get('output_price'))}")
    lines.append("")
    temp_path = payload_path.with_suffix(f"{payload_path.suffix}.tmp")
    temp_path.write_text("\n".join(lines), encoding="utf-8")
    temp_path.replace(payload_path)


def _yaml_scalar(value: object) -> str:
    normalized = _normalize_price(value)
    if normalized is None:
        return "null"
    return format(normalized, "g")


def _load_known_openai_model_ids(*, catalog_path: str, overrides_path: str, manual_config_path: str) -> list[str]:
    known_model_ids: set[str] = set()
    for source_path in (catalog_path, overrides_path, manual_config_path):
        payload_path = Path(source_path)
        if not payload_path.exists():
            continue
        if payload_path.suffix.lower() in {".yaml", ".yml"}:
            known_model_ids.update(_load_manual_pricing_yaml(path=str(payload_path)).keys())
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            for item in payload.get("entries") or []:
                if isinstance(item, dict):
                    model_id = resolve_openai_base_model_id(item.get("model_id") or "")
                    if model_id:
                        known_model_ids.add(model_id)
            for item in payload.get("models") or []:
                if isinstance(item, dict):
                    model_id = resolve_openai_base_model_id(item.get("model_id") or "")
                    if model_id:
                        known_model_ids.add(model_id)
    classification_path = Path(catalog_path).with_name("provider_model_classifications.json")
    if classification_path.exists():
        try:
            payload = json.loads(classification_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        for item in payload.get("entries") or [] if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            model_id = resolve_openai_base_model_id(item.get("model_id") or "")
            if model_id:
                known_model_ids.add(model_id)
    return sorted(known_model_ids)


def _build_manual_pricing_yaml_models(
    *,
    model_ids: list[str],
    existing_yaml_overrides: dict[str, dict],
    snapshot_entries: dict[str, OpenAIPricingEntry],
    json_overrides: dict[str, dict],
) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for model_id in model_ids:
        yaml_override = existing_yaml_overrides.get(model_id) or {}
        snapshot_entry = snapshot_entries.get(model_id)
        json_override = json_overrides.get(model_id) or {}
        if yaml_override:
            input_price = yaml_override.get("input_price")
            cached_input_price = yaml_override.get("cached_input_price")
            output_price = yaml_override.get("output_price")
        elif snapshot_entry is not None and snapshot_entry.pricing_basis == "per_1m_tokens":
            input_price = snapshot_entry.input_price
            cached_input_price = snapshot_entry.cached_input_price
            output_price = snapshot_entry.output_price
        elif _normalize_string(json_override.get("pricing_basis")).lower() == "per_1m_tokens":
            input_price = _normalize_price(json_override.get("input_price"))
            cached_input_price = _normalize_price(json_override.get("cached_input_price"))
            output_price = _normalize_price(json_override.get("output_price"))
        else:
            input_price = None
            cached_input_price = None
            output_price = None
        models.append(
            {
                "model_id": model_id,
                "input_price": input_price,
                "cached_input_price": cached_input_price,
                "output_price": output_price,
            }
        )
    return models


def _apply_overrides(*, entries: list[OpenAIPricingEntry], overrides: dict[str, dict], source_url: str, extracted_at: str) -> list[OpenAIPricingEntry]:
    if not overrides:
        return entries
    by_id = {entry.model_id: entry for entry in entries}
    for model_id, raw in overrides.items():
        existing = by_id.get(model_id)
        family = _normalize_family(raw.get("family"), model_id=model_id) if existing is None else existing.family
        basis = _normalize_string(raw.get("pricing_basis")).lower() or (existing.pricing_basis if existing is not None else _default_pricing_basis_for_family(family))
        if basis not in _CANONICAL_PRICING_BASIS:
            continue
        input_price = _normalize_price(raw.get("input_price"))
        cached_input_price = _normalize_price(raw.get("cached_input_price"))
        output_price = _normalize_price(raw.get("output_price"))
        input_price, cached_input_price, output_price = _sanitize_non_applicable_price_fields(
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
        )
        normalized_price = _normalize_price(raw.get("normalized_price"))
        if existing is not None:
            if input_price is None:
                input_price = existing.input_price
            if cached_input_price is None:
                cached_input_price = existing.cached_input_price
            if output_price is None:
                output_price = existing.output_price
            if normalized_price is None:
                normalized_price = existing.normalized_price
        normalized_unit = _normalize_string(raw.get("normalized_unit"))
        if not normalized_unit:
            normalized_unit = existing.normalized_unit if existing is not None else _default_normalized_unit(basis)
        notes = list(existing.notes) if existing is not None else []
        notes.append("pricing_override_applied")
        basis, input_price, cached_input_price, output_price, normalized_price, normalized_unit, notes = _enforce_family_pricing_rules(
            family=family,
            basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
            normalized_price=normalized_price,
            normalized_unit=normalized_unit,
            notes=notes,
        )
        by_id[model_id] = OpenAIPricingEntry(
            model_id=model_id,
            family=family,
            pricing_basis=basis,
            input_price=input_price,
            cached_input_price=cached_input_price,
            output_price=output_price,
            normalized_price=normalized_price,
            normalized_unit=normalized_unit,
            notes=sorted(set(note for note in notes if _normalize_string(note))),
            source_url="manual://pricing_overrides" if source_url.startswith("http") else source_url,
            extracted_at=extracted_at,
            extraction_status="manual_override" if existing is None else existing.extraction_status,
        )
    return sorted(by_id.values(), key=lambda entry: entry.model_id)


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
        overrides_path: str = DEFAULT_OPENAI_PRICING_OVERRIDES_PATH,
        manual_config_path: str = DEFAULT_OPENAI_PRICING_MANUAL_CONFIG_PATH,
        text_cache_path: str = DEFAULT_OPENAI_PRICING_TEXT_CACHE_PATH,
        normalized_text_cache_path: str = DEFAULT_OPENAI_PRICING_NORMALIZED_TEXT_CACHE_PATH,
        sections_cache_path: str = DEFAULT_OPENAI_PRICING_SECTIONS_CACHE_PATH,
        debug_response_path: str | None = None,
        prompt_sent_path: str | None = None,
    ) -> None:
        self._logger = logger
        resolved_overrides_path = overrides_path
        if (
            overrides_path == DEFAULT_OPENAI_PRICING_OVERRIDES_PATH
            and catalog_path != DEFAULT_OPENAI_PRICING_CATALOG_PATH
        ):
            resolved_overrides_path = str(Path(catalog_path).with_name(Path(DEFAULT_OPENAI_PRICING_OVERRIDES_PATH).name))
        self._source_urls = source_urls or get_configured_openai_pricing_source_urls()
        self._refresh_interval_seconds = int(refresh_interval_seconds)
        self._stale_tolerance_seconds = int(stale_tolerance_seconds)
        self._fetcher = fetcher or OpenAIPricingHTMLFetcher(
            timeout_seconds=float(os.environ.get("SYNTHIA_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS") or DEFAULT_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS),
            retry_count=int(os.environ.get("SYNTHIA_OPENAI_PRICING_FETCH_RETRY_COUNT") or DEFAULT_OPENAI_PRICING_FETCH_RETRY_COUNT),
        )
        self._parser = parser or OpenAIPricingPageParser()
        self._store = store or OpenAIPricingCatalogStore(path=catalog_path, logger=logger)
        self._overrides_path = resolved_overrides_path
        self._manual_config_path = str(manual_config_path or DEFAULT_OPENAI_PRICING_MANUAL_CONFIG_PATH).strip() or DEFAULT_OPENAI_PRICING_MANUAL_CONFIG_PATH
        self._text_cache_path = Path(text_cache_path)
        self._normalized_text_cache_path = Path(normalized_text_cache_path)
        self._sections_cache_path = Path(sections_cache_path)
        configured_debug_path = (
            debug_response_path
            if debug_response_path is not None
            else os.environ.get("SYNTHIA_OPENAI_PRICING_DEBUG_RESPONSE_PATH", DEFAULT_OPENAI_PRICING_DEBUG_RESPONSE_PATH)
        )
        self._debug_response_path = (
            Path(str(configured_debug_path).strip())
            if str(configured_debug_path or "").strip()
            else None
        )
        configured_prompt_path = (
            prompt_sent_path
            if prompt_sent_path is not None
            else os.environ.get("SYNTHIA_OPENAI_PRICING_PROMPT_SENT_PATH", DEFAULT_OPENAI_PRICING_PROMPT_SENT_PATH)
        )
        self._prompt_sent_path = (
            Path(str(configured_prompt_path).strip())
            if str(configured_prompt_path or "").strip()
            else None
        )
        self._ensure_manual_pricing_config()

    def _ensure_manual_pricing_config(self) -> None:
        try:
            snapshot = self.load_snapshot()
            snapshot_entries = {
                entry.model_id: entry
                for entry in (snapshot.entries if snapshot is not None else [])
            }
            json_overrides = _load_pricing_overrides(path=self._overrides_path)
            existing_yaml_overrides = _load_manual_pricing_yaml(path=self._manual_config_path)
            known_model_ids = _load_known_openai_model_ids(
                catalog_path=self._store.path if self._store is not None and hasattr(self._store, "path") else DEFAULT_OPENAI_PRICING_CATALOG_PATH,
                overrides_path=self._overrides_path,
                manual_config_path=self._manual_config_path,
            )
            if not known_model_ids:
                return
            yaml_models = _build_manual_pricing_yaml_models(
                model_ids=known_model_ids,
                existing_yaml_overrides=existing_yaml_overrides,
                snapshot_entries=snapshot_entries,
                json_overrides=json_overrides,
            )
            _save_manual_pricing_yaml(path=self._manual_config_path, models=yaml_models)
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[openai-manual-pricing-config-sync-failed] %s", {"path": self._manual_config_path})

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

    def _save_pricing_text_cache(
        self,
        *,
        source_url: str,
        fetched_at: str,
        fetch_status: str,
        page_text: str,
    ) -> None:
        payload = {
            "source_url": source_url,
            "fetched_at": fetched_at,
            "fetch_status": fetch_status,
            "text_length": len(page_text),
            "text": page_text,
        }
        self._text_cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._text_cache_path.with_suffix(f"{self._text_cache_path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._text_cache_path)

    def _normalize_pricing_source_text(self, *, page_text: str) -> str:
        text = str(page_text or "")
        lines = text.splitlines()
        normalized_lines: list[str] = []
        in_style_block = False
        in_script_block = False
        for raw_line in lines:
            line = raw_line.rstrip()
            lower = line.strip().lower()
            if "<style" in lower:
                in_style_block = True
            if "<script" in lower:
                in_script_block = True
            if in_style_block:
                if "</style>" in lower:
                    in_style_block = False
                continue
            if in_script_block:
                if "</script>" in lower:
                    in_script_block = False
                continue
            if lower.startswith("import ") or lower.startswith("export "):
                continue
            if lower.startswith("const ") and "=" in lower:
                continue
            if lower.startswith("function "):
                continue
            if lower.startswith("<div") or lower.startswith("</div") or lower.startswith("<span") or lower.startswith("</span"):
                continue
            if lower.startswith("class=") or lower.startswith("classname="):
                continue
            compact = line.strip()
            if not compact:
                if normalized_lines and normalized_lines[-1] == "":
                    continue
                normalized_lines.append("")
                continue
            normalized_lines.append(compact)
        normalized_text = "\n".join(normalized_lines).strip()
        return normalized_text

    def _save_normalized_pricing_text_cache(
        self,
        *,
        source_url: str,
        fetched_at: str,
        fetch_status: str,
        normalized_text: str,
    ) -> None:
        payload = {
            "source_url": source_url,
            "fetched_at": fetched_at,
            "fetch_status": fetch_status,
            "text_length": len(normalized_text),
            "text": normalized_text,
        }
        self._normalized_text_cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._normalized_text_cache_path.with_suffix(f"{self._normalized_text_cache_path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._normalized_text_cache_path)

    def _split_pricing_source_sections(self, *, normalized_text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {key: [] for key in _PRICING_SECTION_KEYS}
        current_section: str | None = None

        def _normalize_heading_candidate(raw_line: str) -> str:
            heading = raw_line.strip()
            heading = heading.lstrip("#").strip()
            heading = re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*", "", heading)
            heading = heading.replace("&", " and ")
            heading = heading.replace("/", " ")
            heading = re.sub(r"[^a-z0-9 ]+", " ", heading.lower())
            heading = re.sub(r"\s+", " ", heading).strip()
            return heading

        def _resolve_section_key(raw_line: str) -> str | None:
            candidate = _normalize_heading_candidate(raw_line)
            if not candidate:
                return None
            for section_key, aliases in _PRICING_SECTION_ALIASES.items():
                for alias in aliases:
                    if candidate == alias or candidate.startswith(f"{alias} "):
                        return section_key
            return None

        for raw_line in str(normalized_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                if current_section and sections[current_section] and sections[current_section][-1] != "":
                    sections[current_section].append("")
                continue

            detected = _resolve_section_key(line)
            if detected is not None:
                current_section = detected
                sections[current_section].append(line)
                continue

            if current_section is not None:
                sections[current_section].append(line)

        normalized_sections: dict[str, str] = {}
        for key, value in sections.items():
            text = "\n".join(value).strip()
            if not text:
                normalized_sections[key] = ""
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            content_lines = lines[1:] if len(lines) > 1 else []
            content_blob = "\n".join(content_lines).lower()
            has_pricing_content = bool(re.search(r"\$[0-9]+(?:\.[0-9]+)?", content_blob)) or (
                "free of charge" in content_blob
            )
            normalized_sections[key] = text if has_pricing_content else ""
        return normalized_sections

    def _save_pricing_sections_cache(
        self,
        *,
        source_url: str,
        fetched_at: str,
        fetch_status: str,
        sections: dict[str, str],
        extracted_sections: dict[str, str] | None = None,
        family_diagnostics: dict[str, dict] | None = None,
    ) -> None:
        payload = {
            "source_url": source_url,
            "fetched_at": fetched_at,
            "fetch_status": fetch_status,
            "sections": {
                name: {
                    "line_count": len([line for line in text.splitlines() if line.strip()]),
                    "text_length": len(text),
                    "text": text,
                }
                for name, text in sections.items()
            },
        }
        if extracted_sections:
            payload["extracted_sections"] = {
                name: {
                    "line_count": len([line for line in text.splitlines() if line.strip()]),
                    "text_length": len(text),
                    "text": text,
                }
                for name, text in extracted_sections.items()
            }
        if family_diagnostics:
            payload["family_diagnostics"] = family_diagnostics
        self._sections_cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._sections_cache_path.with_suffix(f"{self._sections_cache_path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._sections_cache_path)

    def _extract_text_token_pricing_rows(self, *, section_text: str, target_model_ids: list[str]) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="llm")
        return self._extract_target_pricing_rows_from_text(section_text=section_text, target_tokens=target_tokens)

    def _resolve_target_model_tokens(self, *, target_model_ids: list[str], family: str) -> list[str]:
        return sorted(
            {
                _normalize_string(resolve_openai_base_model_id(model_id)).lower()
                for model_id in target_model_ids
                if _normalize_family(None, model_id=model_id) == family
            }
        )

    def _resolve_target_model_tokens_for_families(self, *, target_model_ids: list[str], families: set[str]) -> list[str]:
        return sorted(
            {
                _normalize_string(resolve_openai_base_model_id(model_id)).lower()
                for model_id in target_model_ids
                if _normalize_family(None, model_id=model_id) in families
            }
        )

    def _extract_target_pricing_rows_from_text(self, *, section_text: str, target_tokens: list[str]) -> str:
        if not target_tokens:
            return ""
        blocks: list[str] = []
        current: list[str] = []
        for raw_line in str(section_text or "").splitlines():
            line = raw_line.strip()
            if line:
                current.append(line)
                continue
            if current:
                blocks.append("\n".join(current))
                current = []
        if current:
            blocks.append("\n".join(current))

        extracted: list[str] = []
        for block in blocks:
            lower = block.lower()
            has_target = any(token in lower for token in target_tokens)
            has_price_data = ("$" in block) or bool(re.search(r"\b[0-9]+(?:\.[0-9]+)?\b", block))
            if has_target and has_price_data:
                extracted.append(block)
        return "\n\n".join(extracted).strip()

    def _extract_audio_realtime_pricing_rows(
        self,
        *,
        audio_tokens_section: str,
        transcription_section: str,
        target_model_ids: list[str],
    ) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="realtime_voice")
        audio_rows = self._extract_target_pricing_rows_from_text(section_text=audio_tokens_section, target_tokens=target_tokens)
        transcription_rows = self._extract_target_pricing_rows_from_text(
            section_text=transcription_section,
            target_tokens=target_tokens,
        )
        merged = [text for text in [audio_rows, transcription_rows] if text]
        if not merged:
            return ""
        deduped: list[str] = []
        seen: set[str] = set()
        for block in "\n\n".join(merged).split("\n\n"):
            compact = block.strip()
            if compact and compact not in seen:
                deduped.append(compact)
                seen.add(compact)
        return "\n\n".join(deduped).strip()

    def _extract_image_generation_pricing_rows(self, *, section_text: str, target_model_ids: list[str]) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="image_generation")
        if not target_tokens:
            return ""
        base_rows = self._extract_target_pricing_rows_from_text(section_text=section_text, target_tokens=target_tokens)
        if not base_rows:
            return ""

        selected_blocks: list[str] = []
        for block in base_rows.split("\n\n"):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            lower_lines = [line.lower() for line in lines]
            preferred = [
                lines[index]
                for index, lower in enumerate(lower_lines)
                if ("1024x1536" in lower or "medium" in lower) and ("$" in lines[index] or re.search(r"\b[0-9]+(?:\.[0-9]+)?\b", lines[index]))
            ]
            if preferred:
                model_lines = [
                    lines[index]
                    for index, lower in enumerate(lower_lines)
                    if any(token in lower for token in target_tokens)
                ]
                selected = model_lines[:1] + preferred
                selected_blocks.append("\n".join(dict.fromkeys(selected)))
            else:
                selected_blocks.append("\n".join(lines))
        return "\n\n".join(selected_blocks).strip()

    def _extract_video_pricing_rows(self, *, section_text: str, target_model_ids: list[str]) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="video_generation")
        return self._extract_target_pricing_rows_from_text(section_text=section_text, target_tokens=target_tokens)

    def _extract_stt_tts_other_pricing_rows(
        self,
        *,
        other_models_section: str,
        transcription_section: str,
        target_model_ids: list[str],
    ) -> str:
        target_tokens = self._resolve_target_model_tokens_for_families(
            target_model_ids=target_model_ids,
            families={"speech_to_text", "text_to_speech"},
        )
        other_rows = self._extract_target_pricing_rows_from_text(
            section_text=other_models_section,
            target_tokens=target_tokens,
        )
        transcription_rows = self._extract_target_pricing_rows_from_text(
            section_text=transcription_section,
            target_tokens=target_tokens,
        )
        merged = [text for text in [other_rows, transcription_rows] if text]
        if not merged:
            return ""
        deduped: list[str] = []
        seen: set[str] = set()
        for block in "\n\n".join(merged).split("\n\n"):
            compact = block.strip()
            if compact and compact not in seen:
                deduped.append(compact)
                seen.add(compact)
        return "\n\n".join(deduped).strip()

    def _extract_embeddings_pricing_rows(self, *, section_text: str, target_model_ids: list[str]) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="embeddings")
        base_rows = self._extract_target_pricing_rows_from_text(section_text=section_text, target_tokens=target_tokens)
        if not base_rows:
            return ""
        selected_blocks: list[str] = []
        for block in base_rows.split("\n\n"):
            lower = block.lower()
            if "/ 1m" in lower or "/1m" in lower or "1m token" in lower or "per 1m token" in lower:
                selected_blocks.append(block.strip())
        if not selected_blocks:
            return base_rows
        return "\n\n".join(selected_blocks).strip()

    def _extract_moderation_pricing_rows(self, *, section_text: str, target_model_ids: list[str]) -> str:
        target_tokens = self._resolve_target_model_tokens(target_model_ids=target_model_ids, family="moderation")
        if not target_tokens:
            return ""
        blocks: list[str] = []
        current: list[str] = []
        for raw_line in str(section_text or "").splitlines():
            line = raw_line.strip()
            if line:
                current.append(line)
                continue
            if current:
                blocks.append("\n".join(current))
                current = []
        if current:
            blocks.append("\n".join(current))

        extracted: list[str] = []
        for block in blocks:
            lower = block.lower()
            has_target = any(token in lower for token in target_tokens)
            has_priced = ("$" in block) or bool(re.search(r"\b[0-9]+(?:\.[0-9]+)?\b", block))
            has_free = ("free of charge" in lower) or ("free" in lower)
            if has_target and (has_priced or has_free):
                extracted.append(block.strip())
        return "\n\n".join(extracted).strip()

    def _save_debug_response(self, *, payload: dict) -> None:
        if self._debug_response_path is None:
            return
        self._debug_response_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._debug_response_path.with_suffix(f"{self._debug_response_path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._debug_response_path)

    def _save_prompt_sent(
        self,
        *,
        source_url: str,
        extraction_model: str,
        allowed_model_ids: list[str],
        system_prompt: str,
        user_prompt: str,
    ) -> None:
        if self._prompt_sent_path is None:
            return
        self._prompt_sent_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            f"generated_at: {_iso_now()}",
            f"source_url: {source_url}",
            f"extraction_model: {extraction_model}",
            f"allowed_model_ids: {', '.join(allowed_model_ids)}",
            "",
            "system_prompt:",
            system_prompt,
            "",
            "user_prompt:",
            user_prompt,
            "",
        ]
        tmp = self._prompt_sent_path.with_suffix(f"{self._prompt_sent_path.suffix}.tmp")
        tmp.write_text("\n".join(payload), encoding="utf-8")
        tmp.replace(self._prompt_sent_path)

    async def refresh(
        self,
        *,
        force: bool = False,
        model_ids: list[str] | None = None,
        execute_batch: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> dict:
        previous = self.load_snapshot()
        if not force and previous is not None and not self.should_refresh(previous):
            return {
                "status": "skipped",
                "changed": False,
                "snapshot": previous.model_dump(),
                "notes": ["refresh_interval_not_elapsed"],
            }

        try:
            source_url = ""
            html = ""
            fetched_at = _iso_now()
            fetch_status = "unknown"
            page_text = ""
            markdown_url = str(
                os.environ.get("SYNTHIA_OPENAI_PRICING_MARKDOWN_URL", DEFAULT_OPENAI_PRICING_MARKDOWN_URL) or ""
            ).strip()
            if markdown_url:
                try:
                    markdown_source_url, markdown_text = await self._fetcher.fetch_first_available(urls=[markdown_url])
                    if isinstance(markdown_text, str) and markdown_text:
                        source_url = markdown_source_url
                        fetch_status = "primary_markdown"
                        # Keep the markdown content raw for prompt injection.
                        page_text = markdown_text
                except Exception:
                    if hasattr(self._logger, "warning"):
                        self._logger.warning(
                            "[openai-pricing-markdown-fetch-failed] %s",
                            {"url": markdown_url},
                        )
            if not page_text:
                source_url, html = await self._fetcher.fetch_first_available(urls=self._source_urls)
                fetch_status = "fallback_html"
                page_text = html
            self._save_pricing_text_cache(
                source_url=source_url,
                fetched_at=fetched_at,
                fetch_status=fetch_status,
                page_text=page_text,
            )
            normalized_page_text = self._normalize_pricing_source_text(page_text=page_text)
            self._save_normalized_pricing_text_cache(
                source_url=source_url,
                fetched_at=fetched_at,
                fetch_status=fetch_status,
                normalized_text=normalized_page_text,
            )
            allowed_ids = sorted(
                {
                    _normalize_string(model_id).lower()
                    for model_id in (model_ids or [])
                    if _is_ai_extraction_target_model_id(model_id)
                }
            )
            allowed_map = {
                model_id: _normalize_family(None, model_id=model_id)
                for model_id in allowed_ids
            }
            sectioned_text = self._split_pricing_source_sections(normalized_text=normalized_page_text)
            text_token_rows = self._extract_text_token_pricing_rows(
                section_text=sectioned_text.get("text_tokens", ""),
                target_model_ids=allowed_ids,
            )
            audio_realtime_rows = self._extract_audio_realtime_pricing_rows(
                audio_tokens_section=sectioned_text.get("audio_tokens", ""),
                transcription_section=sectioned_text.get("transcription_and_speech_generation", ""),
                target_model_ids=allowed_ids,
            )
            image_generation_rows = self._extract_image_generation_pricing_rows(
                section_text=sectioned_text.get("image_generation", ""),
                target_model_ids=allowed_ids,
            )
            video_rows = self._extract_video_pricing_rows(
                section_text=sectioned_text.get("video", ""),
                target_model_ids=allowed_ids,
            )
            stt_tts_other_rows = self._extract_stt_tts_other_pricing_rows(
                other_models_section=sectioned_text.get("other_models", ""),
                transcription_section=sectioned_text.get("transcription_and_speech_generation", ""),
                target_model_ids=allowed_ids,
            )
            embeddings_rows = self._extract_embeddings_pricing_rows(
                section_text=sectioned_text.get("embeddings", ""),
                target_model_ids=allowed_ids,
            )
            moderation_rows = self._extract_moderation_pricing_rows(
                section_text=sectioned_text.get("moderation", ""),
                target_model_ids=allowed_ids,
            )
            extracted_sections_payload = {
                "text_tokens_target_rows": text_token_rows,
                "audio_realtime_target_rows": audio_realtime_rows,
                "image_generation_target_rows": image_generation_rows,
                "video_generation_target_rows": video_rows,
                "stt_tts_other_target_rows": stt_tts_other_rows,
                "embeddings_target_rows": embeddings_rows,
                "moderation_target_rows": moderation_rows,
            }
            self._save_pricing_sections_cache(
                source_url=source_url,
                fetched_at=fetched_at,
                fetch_status=fetch_status,
                sections=sectioned_text,
                extracted_sections=extracted_sections_payload,
            )

            extraction_model = _select_pricing_extraction_model(allowed_ids)
            extraction_source = "deterministic_html_parse"
            entries: list[OpenAIPricingEntry] = []

            if execute_batch is not None and extraction_model is not None and allowed_ids:
                extraction_source = "ai_extraction_family_prompts"
                family_target_models: dict[str, list[str]] = {}
                for model_id in allowed_ids:
                    family_target_models.setdefault(allowed_map[model_id], []).append(model_id)
                family_prompt_jobs = [
                    {
                        "prompt_name": "llm_pricing_extraction_prompt",
                        "target_models": [model_id for model_id in allowed_ids if allowed_map.get(model_id) == "llm"],
                        "source_section_name": "text_tokens",
                        "section_text": text_token_rows or sectioned_text.get("text_tokens", "") or normalized_page_text,
                    },
                    {
                        "prompt_name": "realtime_audio_pricing_extraction_prompt",
                        "target_models": [model_id for model_id in allowed_ids if allowed_map.get(model_id) == "realtime_voice"],
                        "source_section_name": "audio_tokens+transcription_and_speech_generation",
                        "section_text": audio_realtime_rows
                        or sectioned_text.get("audio_tokens", "")
                        or sectioned_text.get("transcription_and_speech_generation", ""),
                    },
                    {
                        "prompt_name": "image_generation_pricing_extraction_prompt",
                        "target_models": [model_id for model_id in allowed_ids if allowed_map.get(model_id) == "image_generation"],
                        "source_section_name": "image_generation",
                        "section_text": image_generation_rows or sectioned_text.get("image_generation", ""),
                    },
                    {
                        "prompt_name": "video_pricing_extraction_prompt",
                        "target_models": [model_id for model_id in allowed_ids if allowed_map.get(model_id) == "video_generation"],
                        "source_section_name": "video",
                        "section_text": video_rows or sectioned_text.get("video", ""),
                    },
                    {
                        "prompt_name": "stt_tts_other_pricing_extraction_prompt",
                        "target_models": [
                            model_id
                            for model_id in allowed_ids
                            if allowed_map.get(model_id) in {"speech_to_text", "text_to_speech"}
                        ],
                        "source_section_name": "other_models+transcription_and_speech_generation",
                        "section_text": stt_tts_other_rows
                        or sectioned_text.get("other_models", "")
                        or sectioned_text.get("transcription_and_speech_generation", ""),
                    },
                    {
                        "prompt_name": "embeddings_moderation_pricing_extraction_prompt",
                        "target_models": [
                            model_id
                            for model_id in allowed_ids
                            if allowed_map.get(model_id) in {"embeddings", "moderation"}
                        ],
                        "source_section_name": "embeddings+moderation",
                        "section_text": "\n\n".join(
                            value for value in [embeddings_rows, moderation_rows] if _normalize_string(value)
                        )
                        or "\n\n".join(
                            value
                            for value in [
                                sectioned_text.get("embeddings", ""),
                                sectioned_text.get("moderation", ""),
                            ]
                            if _normalize_string(value)
                        ),
                    },
                ]
                family_prompt_jobs = [job for job in family_prompt_jobs if job["target_models"]]
                prompt_log_blocks: list[str] = []
                family_raw_responses: dict[str, str] = {}
                family_parsed_responses: dict[str, object] = {}
                family_validation_results: dict[str, dict[str, str]] = {}
                family_section_diagnostics: dict[str, dict[str, object]] = {}
                family_statuses: dict[str, str] = {
                    family: ("stale" if family_target_models.get(family) else "stale")
                    for family in sorted(_CANONICAL_FAMILIES)
                }
                merged_entries: dict[str, OpenAIPricingEntry] = {}

                for job in family_prompt_jobs:
                    system_prompt, user_prompt = _build_family_pricing_extraction_prompt(
                        prompt_name=str(job["prompt_name"]),
                        model_ids=list(job["target_models"]),
                        section_text=str(job["section_text"] or ""),
                    )
                    prompt_log_blocks.append(
                        "\n".join(
                            [
                                f"[{job['prompt_name']}]",
                                f"target_models: {', '.join(job['target_models'])}",
                                "",
                                user_prompt,
                            ]
                        )
                    )
                    raw = await execute_batch(extraction_model, system_prompt, user_prompt)
                    prompt_name = str(job["prompt_name"])
                    source_section_name = str(job.get("source_section_name") or "unknown")
                    family_raw_responses[prompt_name] = raw
                    family_section_diagnostics[prompt_name] = {
                        "target_models": list(job["target_models"]),
                        "source_section_name": source_section_name,
                        "normalized_source_snippet": str(job.get("section_text") or "")[:2000],
                        "extraction_prompt_used": {
                            "system_prompt": system_prompt,
                            "user_prompt": user_prompt,
                        },
                        "raw_extraction_result": raw,
                        "validation_result": {"status": "pending", "reason": "pending"},
                    }
                    try:
                        parsed = json.loads(_strip_json_fence(raw))
                    except Exception:
                        family_validation_results[prompt_name] = {
                            "status": "failed",
                            "reason": "json_parse_failed",
                        }
                        family_section_diagnostics[prompt_name]["validation_result"] = family_validation_results[prompt_name]
                        continue
                    family_parsed_responses[prompt_name] = parsed
                    try:
                        normalized_entries = _normalize_extracted_payload(
                            payload=parsed,
                            allowed_models={model_id: allowed_map[model_id] for model_id in job["target_models"]},
                            source_url=source_url,
                            extracted_at=fetched_at,
                        )
                        families = {allowed_map[model_id] for model_id in job["target_models"]}
                        family_errors: list[str] = []
                        for family in sorted(families):
                            family_entries = [entry for entry in normalized_entries if entry.family == family]
                            family_ok, family_error = _validate_family_extracted_entries(
                                family=family,
                                entries=family_entries,
                            )
                            if not family_ok:
                                family_errors.append(family_error or f"family_validation_failed:{family}")
                        if family_errors:
                            family_validation_results[prompt_name] = {
                                "status": "failed",
                                "reason": ";".join(family_errors),
                            }
                            family_section_diagnostics[prompt_name]["validation_result"] = family_validation_results[prompt_name]
                            continue
                    except Exception as family_exc:
                        family_validation_results[prompt_name] = {
                            "status": "failed",
                            "reason": str(family_exc).strip() or type(family_exc).__name__,
                        }
                        family_section_diagnostics[prompt_name]["validation_result"] = family_validation_results[prompt_name]
                        continue
                    family_validation_results[prompt_name] = {"status": "success", "reason": "ok"}
                    family_section_diagnostics[prompt_name]["validation_result"] = family_validation_results[prompt_name]
                    for entry in normalized_entries:
                        merged_entries[entry.model_id] = entry

                if not family_prompt_jobs:
                    raise ValueError("pricing_family_prompt_jobs_empty")

                system_prompt = "Follow the provided user prompt exactly. Return JSON only."
                user_prompt = "\n\n".join(prompt_log_blocks)
                debug_payload = {
                    "generated_at": _iso_now(),
                    "source_url": source_url,
                    "extraction_model": extraction_model,
                    "allowed_model_ids": allowed_ids,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "family_prompt_jobs": family_prompt_jobs,
                    "family_validation_results": family_validation_results,
                    "raw_response": family_raw_responses,
                }
                debug_payload["parsed_response"] = family_parsed_responses
                self._save_debug_response(payload=debug_payload)
                self._save_pricing_sections_cache(
                    source_url=source_url,
                    fetched_at=fetched_at,
                    fetch_status=fetch_status,
                    sections=sectioned_text,
                    extracted_sections=extracted_sections_payload,
                    family_diagnostics=family_section_diagnostics,
                )
                self._save_prompt_sent(
                    source_url=source_url,
                    extraction_model=extraction_model,
                    allowed_model_ids=allowed_ids,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                if any(result.get("status") == "failed" for result in family_validation_results.values()):
                    extraction_source = "ai_extraction_family_prompts_partial"
                failed_families: set[str] = set()
                succeeded_families: set[str] = set()
                for job in family_prompt_jobs:
                    prompt_name = str(job["prompt_name"])
                    status = family_validation_results.get(prompt_name, {}).get("status")
                    families = {allowed_map[model_id] for model_id in job["target_models"]}
                    if status == "success":
                        succeeded_families.update(families)
                    elif status == "failed":
                        failed_families.update(families)

                final_entries: dict[str, OpenAIPricingEntry] = dict(merged_entries)
                previous_entries = list(previous.entries) if previous is not None else []
                for family, target_models in family_target_models.items():
                    if family in succeeded_families:
                        family_statuses[family] = "success"
                        continue
                    previous_family_entries = [
                        entry
                        for entry in previous_entries
                        if entry.family == family and entry.model_id in set(target_models)
                    ]
                    if previous_family_entries:
                        preserved_status = "fallback_used" if family in failed_families else "stale"
                        family_statuses[family] = preserved_status
                        for entry in previous_family_entries:
                            notes = sorted(set(list(entry.notes) + [f"family_{preserved_status}"]))
                            final_entries[entry.model_id] = entry.model_copy(
                                update={"extraction_status": preserved_status, "notes": notes}
                            )
                    else:
                        family_statuses[family] = "failed" if family in failed_families else "stale"
                entries = sorted(final_entries.values(), key=lambda item: item.model_id)
            else:
                if not html:
                    source_url, html = await self._fetcher.fetch_first_available(urls=self._source_urls)
                parsed_entries = self._parser.parse(html=html, source_url=source_url, scraped_at=fetched_at)
                if allowed_ids:
                    parsed_entries = [entry for entry in parsed_entries if entry.model_id in allowed_map]
                entries = parsed_entries

            if not entries:
                raise ValueError("pricing_extraction_empty")

            overrides = _load_pricing_overrides(path=self._overrides_path)
            entries = _apply_overrides(
                entries=entries,
                overrides=overrides,
                source_url=source_url,
                extracted_at=fetched_at,
            )
            is_valid, error = validate_openai_pricing_entries(entries)
            if not is_valid:
                raise ValueError(str(error or "pricing_validation_failed"))

            changes = _build_change_summary(previous, entries)
            snapshot = OpenAIPricingSnapshot(
                source_urls=list(self._source_urls),
                source_url_used=source_url,
                scraped_at=fetched_at,
                refresh_state="ok",
                stale=False,
                last_error=None,
                entries=entries,
                unknown_models=(previous.unknown_models if previous is not None else []),
                changes=changes,
                notes=[f"extraction_source:{extraction_source}", f"fetch_status:{fetch_status}"],
                extraction_model=extraction_model,
                extraction_source=extraction_source,
                text_cache_path=str(self._text_cache_path),
                normalized_text_cache_path=str(self._normalized_text_cache_path),
                sections_cache_path=str(self._sections_cache_path),
            )
            if execute_batch is not None and extraction_model is not None and allowed_ids:
                snapshot.notes = list(snapshot.notes) + [
                    f"family_status:{family}={status}" for family, status in sorted(family_statuses.items())
                ]
            self._store.save(snapshot)
            return {"status": "refreshed", "changed": True, "snapshot": snapshot.model_dump(), "notes": snapshot.notes}
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[openai-pricing-refresh-failed] %s", {"error": str(exc).strip() or type(exc).__name__})
            if previous is not None:
                failed = previous.model_copy(
                    update={
                        "refresh_state": "failed",
                        "stale": self.is_stale(previous),
                        "last_error": str(exc).strip() or type(exc).__name__,
                        "notes": sorted(set(list(previous.notes or []) + ["preserved_last_known_good"])),
                        "text_cache_path": str(self._text_cache_path),
                        "normalized_text_cache_path": str(self._normalized_text_cache_path),
                        "sections_cache_path": str(self._sections_cache_path),
                    }
                )
                self._store.save(failed)
                return {
                    "status": "failed_preserved",
                    "changed": False,
                    "snapshot": failed.model_dump(),
                    "notes": ["preserved_last_known_good"],
                }
            return {
                "status": "failed",
                "changed": False,
                "snapshot": None,
                "notes": [str(exc).strip() or type(exc).__name__],
            }

    def save_manual_pricing(
        self,
        *,
        model_id: str,
        display_name: str | None = None,
        input_price_per_1m: float | None = None,
        output_price_per_1m: float | None = None,
    ) -> dict:
        _ = display_name
        normalized_model_id = resolve_openai_base_model_id(model_id)
        if not normalized_model_id:
            raise ValueError("model_id is required")
        if input_price_per_1m is None and output_price_per_1m is None:
            raise ValueError("at least one manual price is required")
        previous = self.load_snapshot()
        existing_overrides = _load_pricing_overrides(path=self._overrides_path)
        existing_override = existing_overrides.get(normalized_model_id)
        entries = list(previous.entries) if previous is not None else []
        existing = next((entry for entry in entries if entry.model_id == normalized_model_id), None)
        family = _normalize_family(None, model_id=normalized_model_id)
        if existing is not None:
            family = existing.family
        input_price = input_price_per_1m if input_price_per_1m is not None else (existing.input_price if existing is not None else None)
        output_price = output_price_per_1m if output_price_per_1m is not None else (existing.output_price if existing is not None else None)
        manual_entry = OpenAIPricingEntry(
            model_id=normalized_model_id,
            family=family,
            pricing_basis="per_1m_tokens",
            input_price=input_price,
            cached_input_price=(existing.cached_input_price if existing is not None else None),
            output_price=output_price,
            normalized_price=_compute_normalized_price(
                basis="per_1m_tokens",
                input_price=input_price,
                output_price=output_price,
                normalized_price=(existing.normalized_price if existing is not None else None),
            ),
            normalized_unit="per_1m_tokens",
            notes=sorted(set((existing.notes if existing is not None else []) + ["manual_pricing_override"])),
            source_url="manual://local_override",
            extracted_at=_iso_now(),
            extraction_status="manual",
        )
        entries = [entry for entry in entries if entry.model_id != normalized_model_id] + [manual_entry]
        entries.sort(key=lambda entry: entry.model_id)
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
            extraction_model=None,
            extraction_source="manual",
            text_cache_path=str(self._text_cache_path),
            normalized_text_cache_path=str(self._normalized_text_cache_path),
            sections_cache_path=str(self._sections_cache_path),
        )
        self._store.save(snapshot)
        override_payload = {
            "model_id": normalized_model_id,
            "family": family,
            "pricing_basis": "per_1m_tokens",
            "input_price": input_price,
            "output_price": output_price,
            "normalized_price": manual_entry.normalized_price,
            "normalized_unit": "per_1m_tokens",
        }
        if isinstance(existing_override, dict):
            merged_override = dict(existing_override)
            merged_override.update({key: value for key, value in override_payload.items() if value is not None})
            override_payload = merged_override
        existing_overrides[normalized_model_id] = override_payload
        _save_pricing_overrides(path=self._overrides_path, overrides=existing_overrides)
        self._ensure_manual_pricing_config()
        return {"status": "manual_saved", "changed": True, "snapshot": snapshot.model_dump(), "model_id": normalized_model_id}

    def get_pricing_entry(self, model_id: str) -> OpenAIPricingEntry | None:
        yaml_entry = _manual_pricing_yaml_entry(model_id, manual_config_path=self._manual_config_path)
        if yaml_entry is not None:
            return yaml_entry
        snapshot = self.load_snapshot()
        fallback_entry = _fallback_openai_pricing_entry(model_id)
        if snapshot is None:
            return fallback_entry
        target = resolve_openai_base_model_id(model_id)
        for candidate in (_normalize_string(model_id).lower(), target):
            if not candidate:
                continue
            for entry in snapshot.entries:
                if entry.model_id == candidate:
                    if self.is_stale(snapshot):
                        return fallback_entry or entry.model_copy(update={"extraction_status": "stale"})
                    return entry
        return fallback_entry

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
                            "status": "unavailable",
                        }
                    )
                )
                continue

            pricing_input = pricing_entry.input_price if pricing_entry.pricing_basis == "per_1m_tokens" else None
            pricing_output = pricing_entry.output_price if pricing_entry.pricing_basis == "per_1m_tokens" else None
            cached_input = pricing_entry.cached_input_price if pricing_entry.pricing_basis == "per_1m_tokens" else None
            pricing_status = "stale" if stale else pricing_entry.extraction_status
            model_status = getattr(model, "status", "available")
            normalized_model_id = str(getattr(model, "model_id", "") or "").strip().lower()
            if pricing_status == "stale":
                model_status = "degraded"
            elif normalized_model_id.startswith("omni-moderation-") and pricing_status == "fallback_used":
                model_status = "available"
            elif pricing_status not in {"ok", "manual"}:
                model_status = "unavailable"

            merged.append(
                model.model_copy(
                    update={
                        "base_model_id": pricing_entry.model_id,
                        "pricing_input": pricing_input,
                        "pricing_output": pricing_output,
                        "cached_pricing_input": cached_input,
                        "batch_pricing_input": None,
                        "batch_pricing_output": None,
                        "pricing_status": pricing_status,
                        "pricing_source_url": pricing_entry.source_url,
                        "pricing_scraped_at": pricing_entry.extracted_at,
                        "pricing_notes": list(pricing_entry.notes) + [
                            f"pricing_basis:{pricing_entry.pricing_basis}",
                            f"normalized:{pricing_entry.normalized_unit}={pricing_entry.normalized_price}",
                        ],
                        "status": model_status,
                    }
                )
            )
        if snapshot is not None and unknown_models != snapshot.unknown_models:
            updated = snapshot.model_copy(update={"unknown_models": sorted(set(unknown_models))})
            self._store.save(updated)
        return merged, sorted(set(unknown_models))

    def diagnostics_payload(self) -> dict:
        def _stage_statuses(*, source_url_used: str | None, extraction_source: str | None, refresh_state: str, last_error: str | None) -> dict:
            family_stage = "pending"
            if extraction_source == "ai_extraction_family_prompts":
                family_stage = "success"
            elif extraction_source == "ai_extraction_family_prompts_partial":
                family_stage = "partial"
            elif extraction_source == "deterministic_html_parse":
                family_stage = "fallback_used"
            validation_stage = "success" if refresh_state == "ok" and not last_error else "failed"
            return {
                "source_fetched": "success" if _normalize_string(source_url_used) else "failed",
                "source_normalized": "success" if _normalize_string(str(self._normalized_text_cache_path)) else "failed",
                "sections_extracted": "success" if _normalize_string(str(self._sections_cache_path)) else "failed",
                "family_pricing_extracted": family_stage,
                "validation_complete": validation_stage,
            }

        def _family_statuses_from_notes(notes: list[str] | None) -> dict[str, str]:
            statuses: dict[str, str] = {}
            for note in notes or []:
                if not str(note).startswith("family_status:"):
                    continue
                payload = str(note).split("family_status:", 1)[1]
                family, _, status = payload.partition("=")
                if family and status:
                    statuses[family.strip()] = status.strip()
            return statuses

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
                "notes": ["pricing_catalog_missing"],
                "extraction_model": None,
                "extraction_source": None,
                "text_cache_path": str(self._text_cache_path),
                "normalized_text_cache_path": str(self._normalized_text_cache_path),
                "sections_cache_path": str(self._sections_cache_path),
                "stage_statuses": _stage_statuses(
                    source_url_used=None,
                    extraction_source=None,
                    refresh_state="missing",
                    last_error="pricing_catalog_missing",
                ),
                "family_statuses": {},
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
            "extraction_model": snapshot.extraction_model,
            "extraction_source": snapshot.extraction_source,
            "text_cache_path": snapshot.text_cache_path,
            "normalized_text_cache_path": snapshot.normalized_text_cache_path,
            "sections_cache_path": snapshot.sections_cache_path,
            "stage_statuses": _stage_statuses(
                source_url_used=snapshot.source_url_used,
                extraction_source=snapshot.extraction_source,
                refresh_state=snapshot.refresh_state,
                last_error=snapshot.last_error,
            ),
            "family_statuses": _family_statuses_from_notes(snapshot.notes),
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
        manual_config_path=os.environ.get(
            "SYNTHIA_OPENAI_PRICING_MANUAL_CONFIG_PATH",
            DEFAULT_OPENAI_PRICING_MANUAL_CONFIG_PATH,
        ),
    )
    entry = service.get_pricing_entry(model_id)
    if entry is None:
        return None
    return {
        "currency": "usd",
        "input_per_1m_tokens": entry.input_price if entry.pricing_basis == "per_1m_tokens" else None,
        "cached_input_per_1m_tokens": entry.cached_input_price if entry.pricing_basis == "per_1m_tokens" else None,
        "output_per_1m_tokens": entry.output_price if entry.pricing_basis == "per_1m_tokens" else None,
        "batch_input_per_1m_tokens": None,
        "batch_output_per_1m_tokens": None,
        "pricing_status": entry.extraction_status,
        "source_url": entry.source_url,
        "scraped_at": entry.extracted_at,
        "notes": list(entry.notes),
        "pricing_basis": entry.pricing_basis,
        "normalized_price": entry.normalized_price,
        "normalized_unit": entry.normalized_unit,
    }


def _fallback_openai_pricing_entry(model_id: str) -> OpenAIPricingEntry | None:
    normalized_model_id = _normalize_string(model_id).lower()
    target_model_id = resolve_openai_base_model_id(normalized_model_id)
    pricing = _OPENAI_MANUAL_RATE_FALLBACKS.get(normalized_model_id) or _OPENAI_MANUAL_RATE_FALLBACKS.get(target_model_id)
    if not isinstance(pricing, dict):
        return None
    input_price = _normalize_price(pricing.get("input_price"))
    cached_input_price = _normalize_price(pricing.get("cached_input_price"))
    output_price = _normalize_price(pricing.get("output_price"))
    return OpenAIPricingEntry(
        model_id=target_model_id or normalized_model_id,
        family="llm",
        pricing_basis="per_1m_tokens",
        input_price=input_price,
        cached_input_price=cached_input_price,
        output_price=output_price,
        normalized_price=_compute_normalized_price(
            basis="per_1m_tokens",
            input_price=input_price,
            output_price=output_price,
            normalized_price=None,
        ),
        normalized_unit="per_1m_tokens",
        source_url="manual://built_in_gpt54_rates",
        extracted_at=_iso_now(),
        extraction_status="manual",
        notes=["manual_pricing_fallback", "source:user_supplied_gpt54_rates"],
    )


def _manual_pricing_yaml_entry(model_id: str, *, manual_config_path: str) -> OpenAIPricingEntry | None:
    normalized_model_id = resolve_openai_base_model_id(model_id)
    if not normalized_model_id:
        return None
    manual_overrides = _load_manual_pricing_yaml(path=manual_config_path)
    payload = manual_overrides.get(normalized_model_id)
    if not isinstance(payload, dict):
        return None
    input_price = _normalize_price(payload.get("input_price"))
    cached_input_price = _normalize_price(payload.get("cached_input_price"))
    output_price = _normalize_price(payload.get("output_price"))
    if input_price is None and cached_input_price is None and output_price is None:
        return None
    family = _normalize_family(None, model_id=normalized_model_id)
    basis = _default_pricing_basis_for_family(family)
    normalized_unit = _default_normalized_unit(basis)
    if basis == "per_1m_tokens":
        normalized_price = _compute_normalized_price(
            basis=basis,
            input_price=input_price,
            output_price=output_price,
            normalized_price=None,
        )
    else:
        normalized_price = output_price if output_price is not None else input_price
    return OpenAIPricingEntry(
        model_id=normalized_model_id,
        family=family,
        pricing_basis=basis,
        input_price=input_price,
        cached_input_price=cached_input_price if basis == "per_1m_tokens" else None,
        output_price=output_price,
        normalized_price=normalized_price,
        normalized_unit=normalized_unit,
        source_url="manual://yaml_override",
        extracted_at=_iso_now(),
        extraction_status="manual",
        notes=["manual_pricing_yaml_override"],
    )


class _NullLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None
