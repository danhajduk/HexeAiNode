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
          },
        ];
      })
      .filter(Boolean)
  );
}

export function normalizeClientUsagePayload(payload, promptServicePayload = null) {
  const clients = Array.isArray(payload?.clients) ? payload.clients : [];
  const promptServiceMap = buildPromptServiceMap(promptServicePayload);
  return {
    currentMonth: String(payload?.current_month || "").trim(),
    clients: clients.map((client) => ({
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
    })),
  };
}
