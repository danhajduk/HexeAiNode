import { useState } from "react";
import { CardHeader, SeverityIndicator } from "../../../components/uiPrimitives";

function formatUsd(value) {
  const normalized = Number(value);
  if (!Number.isFinite(normalized) || normalized < 0) {
    return "$0.000000";
  }
  return `$${normalized.toFixed(normalized >= 1 ? 2 : 6)}`;
}

function formatPromptLabel(value) {
  const normalized = String(value || "").trim();
  return normalized || "unattributed prompt";
}

function formatPromptMeta(version, registeredAt) {
  const parts = [];
  const normalizedVersion = String(version || "").trim();
  const normalizedRegisteredAt = formatShortDate(registeredAt);
  if (normalizedVersion) {
    parts.push(normalizedVersion);
  }
  if (normalizedRegisteredAt) {
    parts.push(`registered ${normalizedRegisteredAt}`);
  }
  return parts.join(" | ");
}

function formatPromptDetailLine(prompt) {
  const parts = [];
  const promptMeta = formatPromptMeta(prompt?.currentVersion, prompt?.registeredAt);
  if (promptMeta) {
    parts.push(promptMeta);
  }
  if (prompt?.defaultModel) {
    parts.push(`Default ${prompt.defaultModel}`);
  }
  parts.push(`State ${formatPromptState(prompt?.status)}`);
  parts.push(`Access ${formatAccessScope(prompt?.accessScope)}`);
  parts.push(`Owner ${prompt?.ownerService || "n/a"}`);
  if (prompt?.lastReviewedAt || prompt?.reviewReason) {
    const reviewText = `Reviewed ${formatShortDate(prompt?.lastReviewedAt) || "not yet"}${prompt?.reviewReason ? ` (${prompt.reviewReason})` : ""}`;
    parts.push(reviewText);
  }
  return parts.join(" | ");
}

function formatPromptState(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "unknown";
  }
  return normalized.replaceAll("_", " ");
}

function formatAccessScope(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "service";
  }
  return normalized;
}

function matchesPromptFilter(prompt, filter) {
  if (filter === "all") {
    return true;
  }
  return String(prompt?.status || "").trim() === filter;
}

function formatModelLabel(value) {
  const normalized = String(value || "").trim();
  return normalized || "unknown-model";
}

function formatCount(value) {
  const normalized = Number(value);
  if (!Number.isFinite(normalized) || normalized < 0) {
    return "0";
  }
  return new Intl.NumberFormat().format(normalized);
}

function formatGrantWindow(fromValue, toValue) {
  const fromText = formatShortDate(fromValue);
  const toText = formatShortDate(toValue);
  if (!fromText && !toText) {
    return "";
  }
  if (fromText && toText) {
    return `${fromText} - ${toText}`;
  }
  return fromText || toText;
}

function formatShortDate(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(parsed));
}

function formatMonthHeading(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "Current Month";
  }
  const parsed = Date.parse(`${normalized}-01T00:00:00Z`);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(parsed));
}

function formatLocalDateTime(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(parsed));
}

function ClientRegistrationSummary({ client }) {
  const grant = client?.grant || null;
  return (
    <div className="client-usage-metric-block client-summary-block">
      <p className="muted tiny">Client Registration</p>
      <div className="client-usage-metric-grid">
        <span>Client</span>
        <code>{client?.clientLabel || client?.clientId || "n/a"}</code>
        <span>Customer</span>
        <code>{client?.customerId || "n/a"}</code>
        <span>Grant</span>
        <code>{grant?.grantDisplayName || grant?.grantName || "n/a"}</code>
        <span>Grant State</span>
        <code>{grant?.status ? String(grant.status).replaceAll("_", " ") : "n/a"}</code>
        <span>Registered Window</span>
        <code>{formatGrantWindow(grant?.validFrom, grant?.validTo) || "n/a"}</code>
        <span>Total Prompts</span>
        <code>{formatCount(client?.totalPromptCount)}</code>
      </div>
    </div>
  );
}

function UsageBlock({ title, usage }) {
  return (
    <div className="client-usage-metric-block client-summary-block">
      <p className="muted tiny">{title}</p>
      <div className="client-usage-metric-grid">
        <span>Calls</span>
        <code>{formatCount(usage?.calls)}</code>
        <span>Tokens</span>
        <code>{formatCount(usage?.total_tokens)}</code>
        <span>Cost</span>
        <code>{formatUsd(usage?.cost_usd)}</code>
      </div>
    </div>
  );
}

function ModelUsageTable({ rows = [], currentMonthLabel }) {
  if (!rows.length) {
    return null;
  }
  return (
    <div className="client-usage-table-card">
      <div className="client-usage-table-wrap">
        <table className="client-usage-table client-model-usage-table">
          <thead>
            <tr>
              <th rowSpan="2">Model</th>
              <th colSpan="3">Lifetime</th>
              <th colSpan="3">{currentMonthLabel}</th>
            </tr>
            <tr>
              <th>Calls</th>
              <th>Tokens</th>
              <th>Cost</th>
              <th>Calls</th>
              <th>Tokens</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <strong>{formatModelLabel(row.label)}</strong>
                </td>
                <td><code>{formatCount(row.lifetime?.calls)}</code></td>
                <td><code>{formatCount(row.lifetime?.total_tokens)}</code></td>
                <td><code>{formatUsd(row.lifetime?.cost_usd)}</code></td>
                <td><code>{formatCount(row.currentMonth?.calls)}</code></td>
                <td><code>{formatCount(row.currentMonth?.total_tokens)}</code></td>
                <td><code>{formatUsd(row.currentMonth?.cost_usd)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UnusedPromptTable({ prompts = [] }) {
  if (!prompts.length) {
    return null;
  }
  return (
    <div className="client-usage-table-card">
      <div className="client-usage-table-wrap">
        <table className="client-usage-table">
          <thead>
            <tr>
              <th>Prompt</th>
              <th>Created</th>
              <th>Default Model</th>
            </tr>
          </thead>
          <tbody>
            {prompts.map((prompt) => (
              <tr key={`unused:${prompt.promptId}`}>
                <td><strong>{formatPromptLabel(prompt.promptLabel)}</strong></td>
                <td><code>{formatShortDate(prompt.registeredAt) || "n/a"}</code></td>
                <td><code>{prompt.defaultModel || "n/a"}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PromptSection({ client, prompt, currentMonthLabel }) {
  return (
    <div key={`${client.clientId}:used:${prompt.promptId}`} className="client-cost-model-section">
      <div className="client-cost-prompt-header">
        <div className="client-cost-prompt-title-block">
          <div className="client-cost-prompt-title-row">
            <strong>{formatPromptLabel(prompt.promptLabel)}</strong>
            <SeverityIndicator
              tone={String(prompt?.status || "").trim().toLowerCase() === "active" ? "success" : String(prompt?.status || "").trim().toLowerCase() === "review_due" ? "warning" : "meta"}
            >
              <span className="client-cost-prompt-state-pill">
                <span className="health-dot" />
                {formatPromptState(prompt.status)}
              </span>
            </SeverityIndicator>
          </div>
          <p className="muted tiny client-cost-prompt-meta client-cost-prompt-meta-compact">
            {formatPromptDetailLine(prompt)}
          </p>
        </div>
        <div className="client-cost-prompt-costs">
          <span className="muted tiny">Lifetime {formatUsd(prompt?.lifetime?.cost_usd)}</span>
          <span className="muted tiny">{currentMonthLabel} {formatUsd(prompt?.current_month?.cost_usd)}</span>
        </div>
      </div>
      {Array.isArray(prompt.models) && prompt.models.length ? (
        <ModelUsageTable
          currentMonthLabel={currentMonthLabel}
          rows={prompt.models.map((model) => ({
            key: `${client.clientId}:${prompt.promptId}:${model.modelId}`,
            label: model.modelLabel,
            lifetime: model.lifetime,
            currentMonth: model.current_month,
          }))}
        />
      ) : null}
    </div>
  );
}

export function ClientCostCard({
  clients = [],
  currentMonth = "",
  className = "",
}) {
  const currentMonthLabel = formatMonthHeading(currentMonth);
  const [promptFilter, setPromptFilter] = useState("all");
  const visibleClients = clients
    .map((client) => ({
      ...client,
      prompts: Array.isArray(client.prompts)
        ? client.prompts.filter((prompt) => matchesPromptFilter(prompt, promptFilter))
        : [],
      unusedPrompts: Array.isArray(client.unusedPrompts)
        ? client.unusedPrompts.filter((prompt) => matchesPromptFilter(prompt, promptFilter))
        : [],
    }))
    .filter((client) => client.prompts.length > 0 || client.unusedPrompts.length > 0 || promptFilter === "all");
  return (
    <article className={`card ${className}`.trim()}>
      <CardHeader
        title="Client Usage"
        subtitle="Persistent client and prompt usage totals, including lifetime and current-month rollups."
      />
      {clients.length ? (
        <div className="client-cost-list">
          <div className="card-toolbar">
            <label className="muted tiny" htmlFor="client-prompt-filter">Prompt state</label>
            <select
              id="client-prompt-filter"
              value={promptFilter}
              onChange={(event) => setPromptFilter(event.target.value)}
            >
              <option value="all">All prompts</option>
              <option value="review_due">Review due</option>
              <option value="active">Active</option>
            </select>
          </div>
          {visibleClients.length ? visibleClients.map((client) => (
            <section key={client.clientId} className="client-cost-group">
              <div className="client-cost-group-header">
                <div className="client-cost-summary">
                  <strong>{client.clientLabel}</strong>
                  {client.customerId ? <p className="muted tiny">Customer: {client.customerId}</p> : null}
                </div>
              </div>
              <div className="client-usage-summary-grid">
                <ClientRegistrationSummary client={client} />
                <UsageBlock title="Lifetime" usage={client.lifetime} />
                <UsageBlock title={currentMonthLabel} usage={client.current_month} />
              </div>
              <div className="client-cost-prompt-list">
                {client.prompts.map((prompt) => (
                  <PromptSection key={`${client.clientId}:used:${prompt.promptId}`} client={client} prompt={prompt} currentMonthLabel={currentMonthLabel} />
                ))}
                {client.unusedPrompts?.length ? (
                  <div className="client-unused-prompts-section">
                    <p className="muted tiny">Un-Used Prompts</p>
                    <UnusedPromptTable prompts={client.unusedPrompts} />
                  </div>
                ) : null}
              </div>
            </section>
          )) : (
            <p className="muted tiny">No prompts match the selected prompt-state filter.</p>
          )}
        </div>
      ) : (
        <p className="muted tiny">No persistent client usage history is available yet.</p>
      )}
    </article>
  );
}
