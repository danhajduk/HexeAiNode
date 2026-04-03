import { CardHeader, HealthIndicator, StageBadge } from "../../components/uiPrimitives";
import { OperationalShell } from "./OperationalShell";
import { NodeHealthStrip } from "./NodeHealthStrip";
import { DegradedStateBanner } from "./DegradedStateBanner";
import { NodeOverviewCard } from "./cards/NodeOverviewCard";
import { CapabilitySummaryCard } from "./cards/CapabilitySummaryCard";
import { ProviderRefreshCard } from "./cards/ProviderRefreshCard";
import { ResolvedTasksCard } from "./cards/ResolvedTasksCard";
import { RuntimeServicesCard } from "./cards/RuntimeServicesCard";
import { RecentActivityCard } from "./cards/RecentActivityCard";
import { ClientCostCard } from "./cards/ClientCostCard";
import { OperationalActionsCard } from "./cards/OperationalActionsCard";
import { DiagnosticsPage } from "../diagnostics/DiagnosticsPage";

function maskOnboardingRef(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "none";
  }
  if (normalized === "operational") {
    return normalized;
  }
  if (normalized.length <= 7) {
    return `**********${normalized}`;
  }
  return `**********${normalized.slice(-7)}`;
}

function getTelemetryAgeSeconds(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return null;
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return Math.max(0, Math.floor((Date.now() - parsed) / 1000));
}

function formatTelemetryAge(value) {
  if (value === null || value === undefined) {
    return "none";
  }
  if (value < 60) {
    return `${value}s`;
  }
  if (value < 3600) {
    return `${Math.floor(value / 60)}m`;
  }
  if (value < 86400) {
    return `${Math.floor(value / 3600)}h`;
  }
  return `${Math.floor(value / 86400)}d`;
}

function telemetryFreshnessFromAge(ageSeconds, connected) {
  if (!connected) {
    return "offline";
  }
  if (ageSeconds === null) {
    return "unknown";
  }
  if (ageSeconds <= 300) {
    return "fresh";
  }
  if (ageSeconds <= 1800) {
    return "stale";
  }
  return "inactive";
}

export function OperationalDashboard({
  currentSection,
  sections = [],
  healthStripProps,
  degradedBanner,
  overviewCardProps,
  coreConnection,
  runtimeHealth,
  capabilitySummaryProps,
  providerRefreshProps,
  resolvedTasks = [],
  runtimeServicesProps,
  operationalActions,
  activityItems = [],
  clientCostItems = [],
  clientUsageMonth = "",
  onboardingSteps = [],
  onboardingProgress = {},
  pendingApprovalNodeId,
  diagnosticsProps,
}) {
  const telemetryAgeSeconds = getTelemetryAgeSeconds(runtimeHealth?.lastTelemetryTimestamp);
  const telemetryFreshness = telemetryFreshnessFromAge(telemetryAgeSeconds, coreConnection?.connected);

  return (
    <OperationalShell
      currentSection={currentSection}
      sections={sections}
      healthStrip={<NodeHealthStrip {...healthStripProps} />}
    >
      <section className="grid operational-dashboard-grid">
        {degradedBanner ? <DegradedStateBanner {...degradedBanner} /> : null}

        {currentSection === "overview" ? (
          <>
            <NodeOverviewCard {...overviewCardProps} />
            {coreConnection?.show ? (
              <article className="card">
                <CardHeader title="Core Connection" subtitle="Trusted Core endpoint metadata and current onboarding linkage." />
                <div className="state-grid">
                  <span>Core ID</span>
                  <code>{coreConnection.pairedCoreId}</code>
                  <span>Core API</span>
                  <code>{coreConnection.coreApiEndpoint || "unavailable"}</code>
                  <span>Operational MQTT</span>
                  <code>
                    {coreConnection.operationalMqttAddress || (coreConnection.connected ? "connected" : "unavailable")}
                  </code>
                  <span>Connection</span>
                  <HealthIndicator value={coreConnection.connected ? "connected" : "disconnected"} />
                  <span>Onboarding Ref</span>
                  <code>{maskOnboardingRef(coreConnection.onboardingReference)}</code>
                  <span>Telemetry Freshness</span>
                  <HealthIndicator value={telemetryFreshness} />
                  <span>Telemetry Age</span>
                  <code>{formatTelemetryAge(telemetryAgeSeconds)}</code>
                </div>
              </article>
            ) : null}
            <OperationalActionsCard {...operationalActions} />
          </>
        ) : null}

        {currentSection === "capabilities" ? (
          <>
            <CapabilitySummaryCard {...capabilitySummaryProps} />
            <ProviderRefreshCard {...providerRefreshProps} />
            <ResolvedTasksCard tasks={resolvedTasks} />
          </>
        ) : null}

        {currentSection === "runtime" ? (
          <>
            <article className="card">
              <CardHeader title="Runtime Health" subtitle="Runtime-only health signals live here instead of repeating across overview cards." />
              <div className="state-grid">
                <span>Core API</span>
                <HealthIndicator value={runtimeHealth.coreApiConnectivity} />
                <span>Operational MQTT</span>
                <HealthIndicator value={runtimeHealth.operationalMqttConnectivity} />
                <span>Governance</span>
                <HealthIndicator value={runtimeHealth.governanceFreshness} />
                <span>Last Telemetry</span>
                <code>{runtimeHealth.lastTelemetryTimestamp || "none"}</code>
                <span>Node Health</span>
                <HealthIndicator value={runtimeHealth.nodeHealthState} />
              </div>
            </article>
            <RuntimeServicesCard {...runtimeServicesProps} />
            <OperationalActionsCard {...operationalActions} />
          </>
        ) : null}

        {currentSection === "activity" ? (
          <>
            <article className="card">
              <CardHeader title="Onboarding" subtitle="Live onboarding progress by lifecycle stage." />
              <div className="progress-list">
                {onboardingSteps.map((step) => {
                  const state = onboardingProgress?.[step.key] || "pending";
                  return (
                    <div className="progress-row" key={step.key}>
                      <span>{step.label}</span>
                      <StageBadge value={state} />
                    </div>
                  );
                })}
              </div>
              {pendingApprovalNodeId ? (
                <p className="muted tiny">
                  Pending approval for node: <code>{pendingApprovalNodeId}</code>
                </p>
              ) : null}
            </article>
            <RecentActivityCard items={activityItems} degraded={Boolean(degradedBanner)} />
          </>
        ) : null}

        {currentSection === "clients" ? (
          <ClientCostCard
            clients={clientCostItems}
            currentMonth={clientUsageMonth}
            className="operational-card-full-span"
          />
        ) : null}

        {currentSection === "diagnostics" ? (
          <DiagnosticsPage {...diagnosticsProps} className="operational-card-full-span" />
        ) : null}
      </section>
    </OperationalShell>
  );
}
