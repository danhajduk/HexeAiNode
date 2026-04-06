import { describe, expect, it } from "vitest";
import { normalizeClientUsagePayload } from "./clientUsageSummary";

describe("client usage summary", () => {
  it("joins prompt service metadata into normalized client usage rows", () => {
    const result = normalizeClientUsagePayload(
      {
        current_month: "2026-04",
        clients: [
          {
            client_id: "client-1",
            customer_id: "customer-1",
            grant: {
              grant_display_name: "Primary Grant",
              grant_id: "grant-1",
              budget_cents: 2500,
            },
            prompts: [
              {
                prompt_id: "prompt-1",
                models: [
                  {
                    model_id: "gpt-4.1-mini",
                  },
                ],
              },
            ],
          },
        ],
      },
      {
        prompt_services: [
          {
            prompt_id: "prompt-1",
            current_version: "v3",
            registered_at: "2026-04-01T00:00:00Z",
            status: "review_due",
            access_scope: "shared",
            owner_service: "service.alpha",
            owner_client_id: "client-1",
            provider_preferences: { default_model: "gpt-5.4-mini" },
            last_reviewed_at: "2026-04-02T00:00:00Z",
            review_reason: "provider_policy_refresh",
          },
          {
            prompt_id: "prompt-2",
            current_version: "v1",
            registered_at: "2026-04-03T00:00:00Z",
            status: "active",
            access_scope: "service",
            owner_service: "client-1",
            provider_preferences: { default_model: "gpt-5.4-nano" },
          },
        ],
      }
    );

    expect(result.currentMonth).toBe("2026-04");
    expect(result.clients[0].grant?.grantDisplayName).toBe("Primary Grant");
    expect(result.clients[0].prompts[0]).toMatchObject({
      promptId: "prompt-1",
      currentVersion: "v3",
      registeredAt: "2026-04-01T00:00:00Z",
      status: "review_due",
      accessScope: "shared",
      ownerService: "service.alpha",
      ownerClientId: "client-1",
      defaultModel: "gpt-5.4-mini",
      lastReviewedAt: "2026-04-02T00:00:00Z",
      reviewReason: "provider_policy_refresh",
      reviewDueAt: "2026-05-02T00:00:00.000Z",
    });
    expect(result.clients[0].prompts[0].models[0].modelId).toBe("gpt-4.1-mini");
    expect(result.clients[0].unusedPrompts[0]).toMatchObject({
      promptId: "prompt-2",
      defaultModel: "gpt-5.4-nano",
      reviewDueAt: "2026-05-03T00:00:00.000Z",
    });
    expect(result.clients[0].totalPromptCount).toBe(2);
  });

  it("falls back safely for missing arrays and identifiers", () => {
    const result = normalizeClientUsagePayload({
      clients: [
        {
          prompts: [
            {
              models: [{}],
            },
          ],
        },
      ],
    });

    expect(result.clients[0].clientId).toBe("unknown-client");
    expect(result.clients[0].prompts[0].promptId).toBe("unattributed-prompt");
    expect(result.clients[0].prompts[0].models[0].modelId).toBe("unknown-model");
  });
});
