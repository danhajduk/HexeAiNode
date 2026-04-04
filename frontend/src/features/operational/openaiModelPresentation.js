import { formatPrice, formatTierLabel, parseIsoTimestamp } from "../../shared/formatters";

export const OPENAI_MODEL_GROUPS = [
  ["llm", "LLM"],
  ["image_generation", "Image Generation"],
  ["video_generation", "Video Generation"],
  ["realtime_voice", "Realtime Voice"],
  ["speech_to_text", "STT"],
  ["text_to_speech", "TTS"],
  ["embeddings", "Embeddings"],
  ["moderation", "Moderation"],
];

export function formatModelFamily(value) {
  const normalized = String(value || "unknown").trim();
  if (!normalized) {
    return "Unknown";
  }
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.toUpperCase() === "LLM" ? "LLM" : part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatNormalizedUnit(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "custom unit";
  }
  return normalized
    .replaceAll("_", " ")
    .replace(/\bper\b/gi, "/")
    .replace(/\s+/g, " ")
    .trim();
}

function formatNormalizedPrice(pricing) {
  if (!pricing || typeof pricing.normalized_price !== "number" || Number.isNaN(pricing.normalized_price)) {
    return "unavailable";
  }
  return `$${pricing.normalized_price.toFixed(pricing.normalized_price >= 1 ? 2 : 3)} ${formatNormalizedUnit(pricing.normalized_unit)}`;
}

export function getModelPricingRows(pricing) {
  if (!pricing || typeof pricing !== "object") {
    return [
      ["Pricing", "unavailable"],
      ["Status", "not cached"],
    ];
  }
  if (pricing.pricing_basis === "per_1m_tokens") {
    return [
      ["Input", formatPrice(pricing.input_per_1m_tokens)],
      ["Output", formatPrice(pricing.output_per_1m_tokens)],
      ["Cached Input", formatPrice(pricing.cached_input_per_1m_tokens)],
    ];
  }
  return [
    ["Pricing", formatNormalizedPrice(pricing)],
    ["Basis", formatModelFamily(pricing.pricing_basis)],
    ["Status", formatTierLabel(pricing.pricing_status || "unavailable")],
  ];
}

export function getCapabilityBadges(capabilityEntry) {
  if (!capabilityEntry || typeof capabilityEntry !== "object") {
    return [];
  }
  const featureFlags = capabilityEntry.feature_flags && typeof capabilityEntry.feature_flags === "object"
    ? capabilityEntry.feature_flags
    : {};
  const badges = [
    featureFlags.chat ? "Chat" : null,
    capabilityEntry.reasoning ? "Reasoning" : null,
    featureFlags.code_generation ? "Code Gen" : null,
    featureFlags.code_review ? "Code Review" : null,
    featureFlags.classification ? "Classification" : null,
    featureFlags.summarization ? "Summarization" : null,
    featureFlags.translation ? "Translation" : null,
    featureFlags.json_output ? "JSON" : null,
    capabilityEntry.structured_output ? "Structured" : null,
    capabilityEntry.tool_calling || featureFlags.function_calling || featureFlags.tool_calling ? "Tools" : null,
    capabilityEntry.long_context ? "Long Context" : null,
    featureFlags.embeddings ? "Embeddings" : null,
    featureFlags.moderation ? "Moderation" : null,
    featureFlags.image_generation ? "Image Gen" : null,
    featureFlags.image_editing ? "Image Edit" : null,
    featureFlags.image_variation ? "Image Variation" : null,
    featureFlags.speech_to_text ? "Speech To Text" : null,
    featureFlags.text_to_speech ? "Text To Speech" : null,
    capabilityEntry.audio_input ? "Audio In" : null,
    capabilityEntry.audio_output ? "Audio Out" : null,
    capabilityEntry.realtime ? "Realtime" : null,
    featureFlags.voice_conversation ? "Voice" : null,
    featureFlags.semantic_search ? "Semantic Search" : null,
    capabilityEntry.vision || featureFlags.vision_input || featureFlags.image_understanding ? "Vision" : null,
  ].filter(Boolean);
  return [...new Set(badges)];
}

export function groupOpenAiCatalogModels(openaiCatalogModels, openaiModelCreatedById) {
  return OPENAI_MODEL_GROUPS.map(([family, label]) => ({
    family,
    label,
    models: openaiCatalogModels
      .filter((model) => model.family === family)
      .slice()
      .sort(
        (left, right) =>
          (Number(openaiModelCreatedById[right.model_id] || 0) || parseIsoTimestamp(right.discovered_at)) -
          (Number(openaiModelCreatedById[left.model_id] || 0) || parseIsoTimestamp(left.discovered_at))
      ),
  })).filter((group) => group.models.length > 0);
}
