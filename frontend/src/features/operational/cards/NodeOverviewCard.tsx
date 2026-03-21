import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

export function NodeOverviewCard({
  nodeId,
  nodeName,
  pairedCoreId,
  softwareVersion,
  lifecycleState,
  trustState,
  pairingTimestamp,
}) {
  return (
    <article className="card">
      <CardHeader title="Node Overview" subtitle="Primary home for identity, lifecycle, and trusted pairing summary." />
      <div className="state-grid">
        <span>Node ID</span>
        <code>{nodeId || "unavailable"}</code>
        <span>Node Name</span>
        <code>{nodeName || "unavailable"}</code>
        <span>Lifecycle</span>
        <StatusBadge value={lifecycleState || "unknown"} />
        <span>Trust</span>
        <StatusBadge value={trustState || "unknown"} />
        <span>Paired Hexe Core</span>
        <code>{pairedCoreId || "not_paired"}</code>
        <span>Software</span>
        <code>{softwareVersion || "unknown"}</code>
        <span>Pairing Timestamp</span>
        <code>{pairingTimestamp || "unavailable"}</code>
      </div>
    </article>
  );
}
