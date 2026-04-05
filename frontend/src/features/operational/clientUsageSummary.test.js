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
            last_reviewed_at: "2026-04-02T00:00:00Z",
            review_reason: "provider_policy_refresh",
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
      lastReviewedAt: "2026-04-02T00:00:00Z",
      reviewReason: "provider_policy_refresh",
    });
    expect(result.clients[0].prompts[0].models[0].modelId).toBe("gpt-4.1-mini");
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
