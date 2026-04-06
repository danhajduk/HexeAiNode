const REVIEW_DUE_WINDOW_DAYS = 30;
const REVIEW_DUE_WINDOW_MS = REVIEW_DUE_WINDOW_DAYS * 24 * 60 * 60 * 1000;

function computeReviewDueAt(promptDetails = {}) {
  const freshnessBase =
    String(promptDetails.lastReviewedAt || "").trim()
    || String(promptDetails.lastUsedAt || "").trim()
    || String(promptDetails.updatedAt || "").trim()
    || String(promptDetails.registeredAt || "").trim();
  if (!freshnessBase) {
    return "";
  }
  const parsed = Date.parse(freshnessBase);
  if (Number.isNaN(parsed)) {
    return "";
  }
  return new Date(parsed + REVIEW_DUE_WINDOW_MS).toISOString();
}

function buildPromptServiceMap(payload) {
  const promptServices = Array.isArray(payload?.prompt_services)
    ? payload.prompt_services
    : Array.isArray(payload?.state?.prompt_services)
      ? payload.state.prompt_services
      : [];
  return new Map(
    promptServices
      .map((prompt) => {
        const promptId = String(prompt?.prompt_id || "").trim();
        if (!promptId) {
          return null;
        }
        return [
          promptId,
          {
            currentVersion: String(prompt?.current_version || "").trim(),
            registeredAt: String(prompt?.registered_at || "").trim(),
            status: String(prompt?.status || "").trim(),
            accessScope: String(prompt?.access_scope || "").trim(),
            ownerService: String(prompt?.owner_service || "").trim(),
            ownerClientId: String(prompt?.owner_client_id || "").trim(),
            defaultModel: String(prompt?.provider_preferences?.default_model || "").trim(),
            updatedAt: String(prompt?.updated_at || "").trim(),
            lastReviewedAt: String(prompt?.last_reviewed_at || "").trim(),
            reviewReason: String(prompt?.review_reason || "").trim(),
            lastUsedAt: String(prompt?.usage?.last_used_at || "").trim(),
          },
        ];
      })
      .filter(Boolean)
  );
}

function createEmptyUsage() {
  return { calls: 0, total_tokens: 0, cost_usd: 0 };
}

function buildPromptEntry(promptId, promptServiceMap) {
  const promptDetails = promptServiceMap.get(promptId) || {};
  return {
    promptId,
    promptLabel: promptId || "unattributed-prompt",
    currentVersion: promptDetails.currentVersion || "",
    registeredAt: promptDetails.registeredAt || "",
    status: promptDetails.status || "",
    accessScope: promptDetails.accessScope || "",
    ownerService: promptDetails.ownerService || "",
    ownerClientId: promptDetails.ownerClientId || "",
    defaultModel: promptDetails.defaultModel || "",
    updatedAt: promptDetails.updatedAt || "",
    lastReviewedAt: promptDetails.lastReviewedAt || "",
    reviewReason: promptDetails.reviewReason || "",
    lastUsedAt: promptDetails.lastUsedAt || "",
    reviewDueAt: computeReviewDueAt(promptDetails),
    lifetime: createEmptyUsage(),
    current_month: createEmptyUsage(),
    models: [],
  };
}

function normalizeClient(client, promptServiceMap) {
  return {
    clientId: String(client?.client_id || "").trim() || "unknown-client",
    clientLabel: String(client?.client_id || "").trim() || "unknown-client",
    customerId: String(client?.customer_id || "").trim(),
    grant: client?.grant && typeof client.grant === "object"
      ? {
          grantDisplayName: String(client.grant?.grant_display_name || "").trim(),
          grantName: String(client.grant?.grant_name || "").trim(),
          grantId: String(client.grant?.grant_id || "").trim(),
          validFrom: String(client.grant?.valid_from || "").trim(),
          validTo: String(client.grant?.valid_to || "").trim(),
          status: String(client.grant?.status || "").trim(),
          budgetCents: Number(client.grant?.budget_cents),
        }
      : null,
    lifetime: client?.lifetime || {},
    current_month: client?.current_month || {},
    prompts: Array.isArray(client?.prompts)
      ? client.prompts.map((prompt) => ({
          promptId: String(prompt?.prompt_id || "").trim() || "unattributed-prompt",
          promptLabel: String(prompt?.prompt_id || "").trim() || "unattributed-prompt",
          currentVersion: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.currentVersion || "",
          registeredAt: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.registeredAt || "",
          status: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.status || "",
          accessScope: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.accessScope || "",
          ownerService: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.ownerService || "",
          ownerClientId: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.ownerClientId || "",
          defaultModel: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.defaultModel || "",
          updatedAt: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.updatedAt || "",
          lastReviewedAt: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.lastReviewedAt || "",
          reviewReason: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.reviewReason || "",
          lastUsedAt: promptServiceMap.get(String(prompt?.prompt_id || "").trim())?.lastUsedAt || "",
          reviewDueAt: computeReviewDueAt(promptServiceMap.get(String(prompt?.prompt_id || "").trim()) || {}),
          lifetime: prompt?.lifetime || {},
          current_month: prompt?.current_month || {},
          models: Array.isArray(prompt?.models)
            ? prompt.models.map((model) => ({
                modelId: String(model?.model_id || "").trim() || "unknown-model",
                modelLabel: String(model?.model_id || "").trim() || "unknown-model",
                lifetime: model?.lifetime || {},
                current_month: model?.current_month || {},
              }))
            : [],
        }))
      : [],
    unusedPrompts: [],
  };
}

export function normalizeClientUsagePayload(payload, promptServicePayload = null) {
  const clients = Array.isArray(payload?.clients) ? payload.clients : [];
  const promptServiceMap = buildPromptServiceMap(promptServicePayload);
  const clientMap = new Map(
    clients.map((client) => {
      const normalizedClient = normalizeClient(client, promptServiceMap);
      return [normalizedClient.clientId, normalizedClient];
    })
  );

  for (const [promptId, promptDetails] of promptServiceMap.entries()) {
    const targetClientId = promptDetails.ownerClientId || promptDetails.ownerService;
    if (!targetClientId) {
      continue;
    }
    if (!clientMap.has(targetClientId)) {
      clientMap.set(targetClientId, {
        clientId: targetClientId,
        clientLabel: targetClientId,
        customerId: "",
        grant: null,
        lifetime: createEmptyUsage(),
        current_month: createEmptyUsage(),
        prompts: [],
        unusedPrompts: [],
      });
    }
    const client = clientMap.get(targetClientId);
    const usedPromptIds = new Set(client.prompts.map((prompt) => prompt.promptId));
    if (!usedPromptIds.has(promptId)) {
      client.unusedPrompts.push(buildPromptEntry(promptId, promptServiceMap));
    }
  }

  return {
    currentMonth: String(payload?.current_month || "").trim(),
    clients: Array.from(clientMap.values()).map((client) => ({
      ...client,
      totalPromptCount: [...new Set([
        ...client.prompts.map((prompt) => prompt.promptId),
        ...client.unusedPrompts.map((prompt) => prompt.promptId),
      ])].length,
    })),
  };
}
