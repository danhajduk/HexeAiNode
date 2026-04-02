import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function formatLocalTimestamp(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }

  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(parsed));
}

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
        <code>{formatLocalTimestamp(pairingTimestamp) || "unavailable"}</code>
      </div>
    </article>
  );
}
