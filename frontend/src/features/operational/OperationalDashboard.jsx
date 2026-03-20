import { CardHeader, HealthIndicator, StageBadge } from "../../components/uiPrimitives";
import { OperationalShell } from "./OperationalShell";
import { NodeHealthStrip } from "./NodeHealthStrip";
import { DegradedStateBanner } from "./DegradedStateBanner";
import { NodeOverviewCard } from "./cards/NodeOverviewCard";
import { CapabilitySummaryCard } from "./cards/CapabilitySummaryCard";
import { ResolvedTasksCard } from "./cards/ResolvedTasksCard";
import { RuntimeServicesCard } from "./cards/RuntimeServicesCard";
import { RecentActivityCard } from "./cards/RecentActivityCard";
import { OperationalActionsCard } from "./cards/OperationalActionsCard";
import { DiagnosticsPage } from "../diagnostics/DiagnosticsPage";

export function OperationalDashboard({
  currentSection,
  sections = [],
  healthStripProps,
  degradedBanner,
  overviewCardProps,
  coreConnection,
  runtimeHealth,
  capabilitySummaryProps,
  resolvedTasks = [],
  runtimeServicesProps,
  operationalActions,
  activityItems = [],
  onboardingSteps = [],
  onboardingProgress = {},
  pendingApprovalNodeId,
  diagnosticsProps,
}) {
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
                  <code>{coreConnection.operationalMqttAddress || "unavailable"}</code>
                  <span>Connection</span>
                  <HealthIndicator value={coreConnection.connected ? "connected" : "disconnected"} />
                  <span>Onboarding Ref</span>
                  <code>{coreConnection.onboardingReference || "none"}</code>
                </div>
              </article>
            ) : null}
            <OperationalActionsCard {...operationalActions} />
          </>
        ) : null}

        {currentSection === "capabilities" ? (
          <>
            <CapabilitySummaryCard {...capabilitySummaryProps} />
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

        {currentSection === "diagnostics" ? <DiagnosticsPage {...diagnosticsProps} /> : null}
      </section>
    </OperationalShell>
  );
}
