import { CardHeader } from "../../../components/uiPrimitives";
import { CompactChipList } from "./CompactChipList";

export function CapabilitySummaryCard({
  enabledProviders = [],
  usableModels = [],
  blockedModels = [],
  featureUnion = [],
  resolvedTaskCount = 0,
  classifierSource,
  capabilityGraphVersion,
  onOpenProviderSetup,
  providerSetupEnabled,
  providerHint,
}) {
  const providerItems = enabledProviders.map((provider) => ({ id: provider, label: provider }));
  const usableModelItems = usableModels.map((modelId) => ({ id: modelId, label: modelId, tone: "meta" }));
  const blockedModelItems = blockedModels.map((entry) => ({
    id: entry?.model_id || "unknown",
    label: `${entry?.model_id || "unknown"}${Array.isArray(entry?.blockers) && entry.blockers.length ? ` · ${entry.blockers.join(", ")}` : ""}`,
    tone: "danger",
  }));
  const featureItems = featureUnion.map((feature) => ({ id: feature, label: feature }));

  return (
    <article className="card capability-summary-card">
      <CardHeader title="Capability Summary" subtitle="Primary home for provider, model, and feature resolution." />
      <div className="row capability-actions">
        <button
          className="btn btn-primary"
          type="button"
          disabled={!providerSetupEnabled}
          onClick={onOpenProviderSetup}
        >
          Setup AI Provider
        </button>
        <span className="muted tiny">{providerHint}</span>
      </div>
      <div className="capability-summary-layout">
        <section className="capability-summary-block">
          <h3>Enabled Providers</h3>
          <CompactChipList items={providerItems} emptyLabel="No providers enabled." maxVisible={4} />
        </section>
        <section className="capability-summary-block">
          <h3>Usable Models</h3>
          <CompactChipList items={usableModelItems} emptyLabel="No usable models available." />
        </section>
        <section className="capability-summary-block">
          <h3>Blocked Models</h3>
          <CompactChipList items={blockedModelItems} emptyLabel="No blocked models." />
        </section>
        <section className="capability-summary-block">
          <h3>Resolved Features</h3>
          <CompactChipList items={featureItems} emptyLabel="No feature union available." />
        </section>
        <div className="state-grid capability-summary-meta">
          <span>Resolved Task Families</span>
          <code>{resolvedTaskCount || 0}</code>
          <span>Classifier Source</span>
          <code>{classifierSource || "unavailable"}</code>
          <span>Capability Graph Version</span>
          <code>{capabilityGraphVersion || "unknown"}</code>
        </div>
      </div>
    </article>
  );
}
