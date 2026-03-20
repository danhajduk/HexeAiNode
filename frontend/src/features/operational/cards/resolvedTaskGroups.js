const CATEGORY_RULES = [
  ["Language", ["classification", "summarization", "generation.text", "translation", "reasoning", "chat"]],
  ["Code", ["coding"]],
  ["Search / Retrieval", ["semantic_search", "knowledge_retrieval", "embedding_generation", "document_indexing"]],
  ["Audio", ["speech", "audio", "voice"]],
  ["Vision", ["image", "vision", "ocr", "object_detection", "document_ocr"]],
  ["Real-time", ["realtime", "streaming", "low_latency"]],
  ["Governance / Moderation / Policy", ["moderation", "policy", "sentiment"]],
];

function categoryForTask(task) {
  const normalized = String(task || "").toLowerCase();
  for (const [category, markers] of CATEGORY_RULES) {
    if (markers.some((marker) => normalized.includes(marker))) {
      return category;
    }
  }
  return "Other";
}

export function groupResolvedTasks(tasks = []) {
  const grouped = new Map();
  tasks.forEach((task) => {
    const category = categoryForTask(task);
    if (!grouped.has(category)) {
      grouped.set(category, []);
    }
    grouped.get(category).push(task);
  });
  return Array.from(grouped.entries()).map(([category, items]) => ({
    category,
    items: items.sort((left, right) => left.localeCompare(right)),
  }));
}
