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
  const fromText = String(fromValue || "").trim();
  const toText = String(toValue || "").trim();
  if (!fromText && !toText) {
    return "";
  }
  if (fromText && toText) {
    return `${fromText} -> ${toText}`;
  }
  return fromText || toText;
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

function formatUsageSummary(usage) {
  return `Calls ${formatCount(usage?.calls)} | Tokens ${formatCount(usage?.total_tokens)} | Cost ${formatUsd(usage?.cost_usd)}`;
}

function UsageBlock({ title, usage }) {
  return (
    <div className="client-usage-metric-block">
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

function UsageTable({ title, nameHeader, nameFormatter, rows = [], currentMonthLabel }) {
  if (!rows.length) {
    return null;
  }
  return (
    <div className="client-usage-table-card">
      <p className="muted tiny">{title}</p>
      <div className="client-usage-table-wrap">
        <table className="client-usage-table">
          <thead>
            <tr>
              <th>{nameHeader}</th>
              <th>Lifetime</th>
              <th>{currentMonthLabel}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <strong>{nameFormatter(row.label)}</strong>
                </td>
                <td>
                  <code>{formatUsageSummary(row.lifetime)}</code>
                </td>
                <td>
                  <code>{formatUsageSummary(row.currentMonth)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ClientCostCard({ clients = [], currentMonth = "", className = "" }) {
  const currentMonthLabel = formatMonthHeading(currentMonth);
  return (
    <article className={`card ${className}`.trim()}>
      <CardHeader
        title="Client Usage"
        subtitle="Persistent client and prompt usage totals, including lifetime and current-month rollups."
      />
      {clients.length ? (
        <div className="client-cost-list">
          {clients.map((client) => (
            <section key={client.clientId} className="client-cost-group">
              <div className="client-cost-group-header">
                <div>
                  <strong>{client.clientLabel}</strong>
                  {client.customerId ? <p className="muted tiny">Customer: {client.customerId}</p> : null}
                  {client.grant?.grantName ? (
                    <div className="client-grant-meta">
                      <p className="muted tiny">Grant: {client.grant.grantName}</p>
                      {formatGrantWindow(client.grant.validFrom, client.grant.validTo) ? (
                        <p className="muted tiny">
                          Valid: {formatGrantWindow(client.grant.validFrom, client.grant.validTo)}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <SeverityIndicator tone="meta">
                  <span>{formatUsd(client?.lifetime?.cost_usd)}</span>
                </SeverityIndicator>
              </div>
              <div className="client-usage-summary-grid">
                <UsageBlock title="Lifetime" usage={client.lifetime} />
                <UsageBlock title={currentMonthLabel} usage={client.current_month} />
              </div>
              <div className="client-cost-prompt-list">
                {client.prompts.map((prompt) => (
                  <div key={`${client.clientId}:${prompt.promptId}`} className="client-cost-model-section">
                    <div className="client-cost-prompt-header">
                      <strong>{formatPromptLabel(prompt.promptLabel)}</strong>
                      <div className="client-cost-prompt-costs">
                        <span className="muted tiny">Lifetime {formatUsd(prompt?.lifetime?.cost_usd)}</span>
                        <span className="muted tiny">{currentMonthLabel} {formatUsd(prompt?.current_month?.cost_usd)}</span>
                      </div>
                    </div>
                    {Array.isArray(prompt.models) && prompt.models.length ? (
                      <UsageTable
                        title="Models"
                        nameHeader="Model"
                        nameFormatter={formatModelLabel}
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
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <p className="muted tiny">No persistent client usage history is available yet.</p>
      )}
    </article>
  );
}
