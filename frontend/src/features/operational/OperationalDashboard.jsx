import { useEffect, useMemo, useState } from "react";

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
import { ScheduledTasksSection } from "./ScheduledTasksSection";
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

function formatMetricValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "pending";
  }
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return String(value);
  }
  return `${numberValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function formatSeconds(value) {
  if (value === null || value === undefined || value === "") {
    return "pending";
  }
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return String(value);
  }
  if (numberValue < 60) {
    return `${numberValue.toLocaleString(undefined, { maximumFractionDigits: 1 })}s`;
  }
  return `${(numberValue / 60).toLocaleString(undefined, { maximumFractionDigits: 1 })}m`;
}

function formatBenchmarkStatus(status, active) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["idle", "running", "swapping"].includes(normalized)) {
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }
  return active ? "Running" : "Idle";
}

const LOCAL_LLM_DISPLAY_NAMES = {
  "qwen3-8b-q4_k_m": "Qwen 8B",
  "qwen3-14b-q4_k_m": "Qwen 14B",
  "gemma-3-12b-it-q4_k_m": "Gemma 12B",
  "mistral-nemo-instruct-2407-q4_k_m": "Mistral",
};
const BENCHMARK_LABEL_OPTIONS = [
  "action_required",
  "customer_support",
  "invoice",
  "marketing",
  "meeting",
  "notification",
  "personal",
  "shipment",
  "spam",
  "unknown",
];

function localLlmDisplayName(modelId) {
  return LOCAL_LLM_DISPLAY_NAMES[String(modelId || "").trim()] || String(modelId || "local").trim() || "local";
}

function localLlmColumnTitle(modelId) {
  return localLlmDisplayName(modelId);
}

function localLlmModelLabel(modelId) {
  const displayName = localLlmDisplayName(modelId);
  const normalized = String(modelId || "").trim();
  return normalized && displayName !== normalized ? `${displayName} · ${normalized}` : displayName;
}

function benchmarkReplayDetail(activeBenchmark) {
  const status = formatBenchmarkStatus(activeBenchmark?.status, activeBenchmark?.active);
  const modelId = activeBenchmark?.current_model_id || "";
  const runningCount = Number(activeBenchmark?.running_count || 0);
  const prefix =
    status === "Running"
      ? "Running on"
      : status === "Swapping"
        ? "Swapping to"
        : status === "Idle"
          ? "Idle"
          : status;
  const modelText = modelId && prefix !== "Idle" ? ` ${localLlmModelLabel(modelId)}` : "";
  const countText = runningCount > 0 ? ` · ${runningCount} prompt${runningCount === 1 ? "" : "s"} active` : "";
  return `${prefix}${modelText}${countText}`;
}

function parseOutputPayload(outputText) {
  let normalized = String(outputText || "").trim();
  if (normalized.startsWith("```")) {
    let lines = normalized.split(/\r?\n/);
    if (lines[0]?.trim().startsWith("```")) {
      lines = lines.slice(1);
    }
    if (lines[lines.length - 1]?.trim() === "```") {
      lines = lines.slice(0, -1);
    }
    normalized = lines.join("\n").trim();
  }
  try {
    const payload = JSON.parse(normalized);
    return payload && typeof payload === "object" ? payload : {};
  } catch {
    return {};
  }
}

function labelSummary({ label, confidence, outputText }) {
  const payload = parseOutputPayload(outputText);
  const labelValue = label || payload.label || "none";
  const score = confidence ?? payload.confidence ?? payload.score;
  return `${labelValue}${score === null || score === undefined || score === "" ? "" : ` (${formatMetricValue(score)})`}`;
}

function outputScore({ confidence, outputText }) {
  const payload = parseOutputPayload(outputText);
  const score = confidence ?? payload.confidence ?? payload.score;
  const numberValue = Number(score);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function outputLabel({ label, outputText }) {
  const payload = parseOutputPayload(outputText);
  return String(label || payload.label || "").trim().toLowerCase();
}

function referenceLabel(comparison) {
  return String(comparison?.correct_label || comparison?.openai?.label || parseOutputPayload(comparison?.openai?.output_text).label || "")
    .trim()
    .toLowerCase();
}

function hasDifferentLabel(comparison, modelIds) {
  if (comparison?.correct_label) {
    return false;
  }
  const reference = referenceLabel(comparison);
  if (!reference) {
    return false;
  }
  const localResults = Array.isArray(comparison?.local_results) ? comparison.local_results : [];
  return modelIds.some((modelId) => {
    const result = localResults.find((item) => item?.model_id === modelId);
    if (!result || result.status !== "completed") {
      return false;
    }
    const localLabel = outputLabel({ label: result.label, outputText: result.output_text });
    return localLabel && localLabel !== reference;
  });
}

function average(values) {
  const numbers = values.map(Number).filter(Number.isFinite);
  if (!numbers.length) {
    return null;
  }
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

function reasoningText(result) {
  const payload = parseOutputPayload(result?.output_text);
  return result?.reasoning || payload.rationale || payload.reasoning || payload.reason || payload.explanation || result?.output_text || "none";
}

function LocalModelCell({ result, modelId }) {
  if (!result) {
    return (
      <div className="benchmark-model-cell">
        <code>{modelId}</code>
        <StageBadge value="pending" />
      </div>
    );
  }
  return (
    <div className="benchmark-model-cell">
      <code>{localLlmDisplayName(result.model_id || modelId)}</code>
      <span className="muted tiny">{result.model_id || modelId}</span>
      <StageBadge value={result.status || "unknown"} />
      <span>{labelSummary({ label: result.label, confidence: result.confidence, outputText: result.output_text })}</span>
      <span className="muted tiny">Tokens {formatMetricValue(result.total_tokens)}</span>
      <span className="muted tiny">VRAM {formatMetricValue(result.vram_used_mib ?? result.vram_delta_mib, " MiB")}</span>
      <span className="muted tiny">GPU {formatMetricValue(result.gpu_util_percent, "%")}</span>
      {result.error ? <span className="error tiny">{result.error}</span> : null}
    </div>
  );
}

function promptName(comparison) {
  return comparison?.prompt_id || comparison?.task_family || "unattributed";
}

function buildLocalModelSummaries({ comparisons, modelIds }) {
  const promptNames = Array.from(new Set(comparisons.map(promptName)));
  return promptNames.flatMap((name) =>
    ["__openai__", ...modelIds].map((modelId) => {
      const completedResults = [];
      let matchedLabels = 0;
      const promptComparisons = comparisons.filter((comparison) => promptName(comparison) === name);
      for (const comparison of promptComparisons) {
        const targetLabel = referenceLabel(comparison);
        const result =
          modelId === "__openai__"
            ? { ...comparison?.openai, status: "completed", total_tokens: comparison?.openai?.usage?.total_tokens }
            : (Array.isArray(comparison?.local_results) ? comparison.local_results : []).find((item) => item?.model_id === modelId);
        if (!result || result.status !== "completed") continue;
        const resultLabel = outputLabel({ label: result.label, outputText: result.output_text });
        if (targetLabel && resultLabel && targetLabel === resultLabel) {
          matchedLabels += 1;
        }
        completedResults.push({
          localScore: outputScore({ confidence: result.confidence, outputText: result.output_text }),
          openAiScore: modelId === "__openai__" ? null : outputScore({ confidence: comparison?.openai?.confidence, outputText: comparison?.openai?.output_text }),
          latency: result.latency_ms,
          vram: result.vram_used_mib ?? result.vram_delta_mib,
          gpu: result.gpu_util_percent,
        });
      }
      const scoreDeltas = completedResults
        .map((item) => (item.localScore !== null && item.openAiScore !== null ? item.localScore - item.openAiScore : null))
        .filter((value) => value !== null);
      return {
        promptName: name,
        modelId,
        completed: completedResults.length,
        matchRate: completedResults.length ? matchedLabels / completedResults.length : null,
        avgScoreDelta: average(scoreDeltas),
        avgLatency: average(completedResults.map((item) => item.latency)),
        avgVram: average(completedResults.map((item) => item.vram)),
        avgGpu: average(completedResults.map((item) => item.gpu)),
      };
    })
  );
}

function LocalLLMSummaryTable({ summaries, currentModelId, modelStatusCounts = {} }) {
  return (
    <div className="client-usage-table-card">
      <div className="client-usage-table-wrap">
        <table className="client-usage-table local-llm-summary-table">
          <thead>
            <tr>
              <th>Prompt</th>
              <th>Model</th>
              <th>State</th>
              <th>Queue</th>
              <th>Completed</th>
              <th>Label Match</th>
              <th>Avg Score Delta</th>
              <th>Avg Latency</th>
              <th>Avg VRAM</th>
              <th>Avg GPU</th>
            </tr>
          </thead>
          <tbody>
            {summaries.length ? (
              summaries.map((summary) => {
                const isLoadedModel = summary.modelId !== "__openai__" && summary.modelId === currentModelId;
                const queueCounts = modelStatusCounts[summary.modelId] || {};
                const pendingCount = Number(queueCounts.pending || 0);
                const runningCount = Number(queueCounts.running || 0);
                const unprocessedCount = pendingCount + runningCount;
                const totalCount =
                  unprocessedCount +
                  Number(queueCounts.completed || 0) +
                  Number(queueCounts.failed || 0);
                return (
                <tr className={isLoadedModel ? "local-llm-summary-row-loaded" : ""} key={`${summary.promptName}-${summary.modelId}`}>
                  <td>
                    <code>{summary.promptName}</code>
                  </td>
                  <td>
                    <code>{summary.modelId === "__openai__" ? "OpenAI" : localLlmDisplayName(summary.modelId)}</code>
                    <span className="muted tiny benchmark-snippet">{summary.modelId === "__openai__" ? "baseline" : summary.modelId}</span>
                  </td>
                  <td>
                    {summary.modelId === "__openai__" ? (
                      <span className="benchmark-state-badge benchmark-state-badge-muted">Baseline</span>
                    ) : isLoadedModel ? (
                      <span className="benchmark-state-badge benchmark-state-badge-loaded">Loaded Now</span>
                    ) : (
                      <span className="benchmark-state-badge">Available</span>
                    )}
                  </td>
                  <td>{summary.modelId === "__openai__" ? "baseline" : `${formatMetricValue(unprocessedCount)} / ${formatMetricValue(totalCount)}`}</td>
                  <td>{formatMetricValue(summary.completed)}</td>
                  <td>
                    {summary.matchRate === null ? "pending" : `${formatMetricValue(summary.matchRate * 100)}%`}
                  </td>
                  <td>
                    {summary.avgScoreDelta === null
                      ? "pending"
                      : `${summary.avgScoreDelta > 0 ? "+" : ""}${formatMetricValue(summary.avgScoreDelta)}`}
                  </td>
                  <td>{formatMetricValue(summary.avgLatency, " ms")}</td>
                  <td>{formatMetricValue(summary.avgVram, " MiB")}</td>
                  <td>{formatMetricValue(summary.avgGpu, "%")}</td>
                </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan="10" className="muted">
                  No local LLM models are configured for this benchmark rotation.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BenchmarkDetailModal({ comparison, modelIds, onClose, onSetCorrectLabel, correctionChanging = false }) {
  const comparisonKey = comparison?.record_id || "";
  const openAiLabel = outputLabel({
    label: comparison?.openai?.label,
    outputText: comparison?.openai?.output_text,
  });
  const [draftCorrectLabel, setDraftCorrectLabel] = useState("");
  useEffect(() => {
    setDraftCorrectLabel(comparison?.correct_label || openAiLabel || "");
  }, [comparisonKey, comparison?.correct_label, openAiLabel]);
  const labelOptions = useMemo(() => {
    const localLabels = (Array.isArray(comparison?.local_results) ? comparison.local_results : [])
      .map((result) => outputLabel({ label: result?.label, outputText: result?.output_text }))
      .filter(Boolean);
    return Array.from(new Set([openAiLabel, ...localLabels, ...BENCHMARK_LABEL_OPTIONS].filter(Boolean)));
  }, [comparison?.local_results, openAiLabel]);
  if (!comparison) {
    return null;
  }
  const localResults = Array.isArray(comparison.local_results) ? comparison.local_results : [];
  const resultsByModel = Object.fromEntries(localResults.map((result) => [result.model_id, result]));
  const reviewStatus = comparison.correct_label ? "approved" : "pending";
  const handleApproveLabel = async () => {
    const approvedLabel = String(draftCorrectLabel || "").trim();
    if (!approvedLabel) {
      return;
    }
    await onSetCorrectLabel?.(comparison.record_id, approvedLabel, "approved in benchmark detail");
  };
  return (
    <section className="modal-overlay pricing-modal-overlay" role="dialog" aria-modal="true" aria-label="Benchmark detail">
      <article className="card modal-card benchmark-detail-modal" style={{ width: "95vw", maxWidth: "calc(100vw - 32px)" }}>
        <div className="benchmark-detail-header">
          <CardHeader title="Benchmark Detail" subtitle={comparison.prompt_id || comparison.task_family || comparison.record_id} />
          <button className="btn btn-primary" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="benchmark-detail-topline">
          <div className="benchmark-detail-panel">
            <h3>Record</h3>
            <div className="state-grid benchmark-detail-grid">
              <span>Record</span>
              <code>{comparison.record_id}</code>
              <span>Prompt</span>
              <code>{comparison.prompt_id || "unattributed"}</code>
              <span>Created</span>
              <code>{comparison.created_at || "unknown"}</code>
              <span>Reference Label</span>
              <code>{referenceLabel(comparison) || "none"}</code>
              <span>Review Status</span>
              <code>{reviewStatus}</code>
            </div>
          </div>
          <div className="benchmark-detail-panel">
            <h3>Scoring Override</h3>
            <div className="state-grid benchmark-detail-grid">
              <span>Correct Label</span>
              <select
                value={draftCorrectLabel}
                onChange={(event) => setDraftCorrectLabel(event.target.value)}
                disabled={!onSetCorrectLabel || correctionChanging}
              >
                <option value="">Choose label</option>
                {labelOptions.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
              <span>Applied To</span>
              <code>OpenAI and local match scoring</code>
              <span>Action</span>
              <button
                className="btn btn-primary"
                type="button"
                onClick={handleApproveLabel}
                disabled={!onSetCorrectLabel || correctionChanging || !draftCorrectLabel}
              >
                {correctionChanging ? "Saving..." : "Approve Label"}
              </button>
            </div>
          </div>
        </div>
        <div className="benchmark-detail-comparison">
          <div className="benchmark-detail-panel benchmark-detail-openai">
            <h3>OpenAI</h3>
            <div className="state-grid benchmark-detail-grid">
            <span>Model</span>
            <code>{comparison.openai?.model_id || "openai"}</code>
            <span>Label</span>
            <code>{labelSummary({ label: comparison.openai?.label, confidence: comparison.openai?.confidence, outputText: comparison.openai?.output_text })}</code>
            <span>Tokens</span>
            <code>{formatMetricValue(comparison.openai?.usage?.total_tokens)}</code>
            <span>Latency</span>
            <code>{formatMetricValue(comparison.openai?.latency_ms, " ms")}</code>
            <span>Reasoning</span>
            <code>{reasoningText(comparison.openai)}</code>
            </div>
          </div>
          <div className="benchmark-detail-local-grid">
            {modelIds.map((modelId) => {
              const result = resultsByModel[modelId];
              return (
                <div className="benchmark-detail-block" key={modelId}>
                  <div className="benchmark-detail-model-heading">
                    <strong>{localLlmDisplayName(modelId)}</strong>
                    <span className="muted tiny">{modelId}</span>
                  </div>
                  {result ? (
                    <div className="state-grid compact-grid benchmark-detail-grid">
                      <span>Status</span>
                      <StageBadge value={result.status || "unknown"} />
                      <span>Label</span>
                      <code>{labelSummary({ label: result.label, confidence: result.confidence, outputText: result.output_text })}</code>
                      <span>Tokens</span>
                      <code>{formatMetricValue(result.total_tokens)}</code>
                      <span>Latency</span>
                      <code>{formatMetricValue(result.latency_ms, " ms")}</code>
                      <span>VRAM</span>
                      <code>{formatMetricValue(result.vram_used_mib ?? result.vram_delta_mib, " MiB")}</code>
                      <span>GPU Util</span>
                      <code>{formatMetricValue(result.gpu_util_percent, "%")}</code>
                      <span>Reasoning</span>
                      <code>{reasoningText(result)}</code>
                    </div>
                  ) : (
                    <p className="muted tiny">Pending replay.</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div className="benchmark-detail-panel">
          <h3>Prompt Input</h3>
          <pre className="benchmark-raw-block">{comparison.input_snippet || "none"}</pre>
        </div>
      </article>
    </section>
  );
}

function LocalLLMBenchmarkTable({
  summary,
  onCycleModel,
  cyclingModel = false,
  onRunLoadedModel,
  runningLoadedModel = false,
  onSetCaptureEnabled,
  captureChanging = false,
  onSetCorrectLabel,
  correctionChanging = false,
}) {
  const [selectedComparison, setSelectedComparison] = useState(null);
  const [promptListCleared, setPromptListCleared] = useState(false);
  const [showOnlyDifferences, setShowOnlyDifferences] = useState(true);
  const comparisons = Array.isArray(summary?.comparisons) ? summary.comparisons : [];
  const configuredModels = Array.isArray(summary?.rotation?.models)
    ? summary.rotation.models.map((model) => model?.id).filter(Boolean)
    : [];
  const discoveredModels = comparisons.flatMap((comparison) =>
    Array.isArray(comparison?.local_results) ? comparison.local_results.map((result) => result?.model_id).filter(Boolean) : []
  );
  const modelIds = Array.from(new Set([...configuredModels, ...discoveredModels])).slice(0, 4);
  const currentModelId = summary?.rotation?.current_model_id || "unknown";
  const activeBenchmarkStatus = formatBenchmarkStatus(summary?.active_benchmark?.status, summary?.active_benchmark?.active);
  const activeBenchmarkDetail = benchmarkReplayDetail(summary?.active_benchmark);
  const pendingPromptCount = Number(summary?.status_counts?.pending || 0);
  const runningPromptCount = Number(summary?.status_counts?.running || 0);
  const completedPromptCount = Number(summary?.status_counts?.completed || 0);
  const failedPromptCount = Number(summary?.status_counts?.failed || 0);
  const unprocessedPromptCount = pendingPromptCount + runningPromptCount;
  const totalPromptCount = unprocessedPromptCount + completedPromptCount + failedPromptCount;
  const unprocessedPromptText = `${formatMetricValue(unprocessedPromptCount)} / ${formatMetricValue(totalPromptCount)}`;
  const lastSwap = summary?.rotation?.last_swap || summary?.active_benchmark?.last_swap || null;
  const swapDuration =
    summary?.active_benchmark?.status === "swapping"
      ? summary?.active_benchmark?.swap_elapsed_seconds
      : lastSwap?.duration_seconds;
  const swapError = lastSwap?.error;
  const modelSummaries = buildLocalModelSummaries({ comparisons, modelIds });
  const modelStatusCounts = summary?.model_status_counts || {};
  const filteredComparisons = showOnlyDifferences
    ? comparisons.filter((comparison) => hasDifferentLabel(comparison, modelIds))
    : comparisons;
  const visibleComparisons = promptListCleared ? [] : filteredComparisons;
  const handleSetCorrectLabel = async (recordId, correctLabel, note) => {
    await onSetCorrectLabel?.(recordId, correctLabel, note);
    setSelectedComparison((current) =>
      current && current.record_id === recordId ? { ...current, correct_label: correctLabel || null, correction_note: note || null } : current
    );
  };

  return (
    <>
      <article className="card operational-card-full-span">
      <CardHeader title="Local LLM Benchmarks" subtitle="OpenAI calls replayed against the local model rotation." />
      <div className="benchmark-toolbar">
        <div className="state-grid compact-grid">
          <span>Loaded Local Model</span>
          <code>{localLlmModelLabel(currentModelId)}</code>
          <span>Last Switch</span>
          <code>{summary?.rotation?.updated_at || "none"}</code>
        </div>
        <div className="row">
          <button className="btn" type="button" onClick={() => setPromptListCleared(true)} disabled={promptListCleared || !comparisons.length}>
            Clear Prompt List
          </button>
          <button className="btn" type="button" onClick={() => setShowOnlyDifferences((value) => !value)} disabled={promptListCleared}>
            {showOnlyDifferences ? "Show All Labels" : "Show Differences Only"}
          </button>
          {promptListCleared ? (
            <button className="btn" type="button" onClick={() => setPromptListCleared(false)}>
              Show Prompts
            </button>
          ) : null}
          <button
            className="btn"
            type="button"
            onClick={() => onSetCaptureEnabled?.(!summary?.capture_enabled)}
            disabled={!onSetCaptureEnabled || captureChanging}
          >
            {captureChanging
              ? "Updating..."
              : summary?.capture_enabled
                ? "Pause Prompt Capture"
                : "Capture OpenAI Prompts"}
          </button>
          <button className="btn btn-primary" type="button" onClick={onCycleModel} disabled={!onCycleModel || cyclingModel}>
            {cyclingModel ? "Loading..." : "Load Next Model"}
          </button>
          <button className="btn btn-primary" type="button" onClick={onRunLoadedModel} disabled={!onRunLoadedModel || runningLoadedModel}>
            {runningLoadedModel ? "Classifying..." : "Classify"}
          </button>
        </div>
      </div>
      <div className="benchmark-status-pills">
        <div className="benchmark-status-pill benchmark-status-pill-emphasis">
          <strong>{localLlmDisplayName(currentModelId)}</strong>
          <span>{currentModelId}</span>
        </div>
        <div className={`benchmark-status-pill${activeBenchmarkStatus === "Running" ? " benchmark-status-pill-running" : ""}`}>
          <strong>Classification Replay</strong>
          <span>{activeBenchmarkDetail}</span>
        </div>
        <div className={`benchmark-status-pill${summary?.capture_enabled ? " benchmark-status-pill-running" : ""}`}>
          <strong>Prompt Capture</strong>
          <span>{summary?.capture_enabled ? "On" : "Off"}</span>
        </div>
        <div className="benchmark-status-pill benchmark-status-pill-emphasis">
          <strong>{unprocessedPromptText}</strong>
          <span>Unprocessed Prompts</span>
        </div>
        <div className="benchmark-status-pill">
          <strong>
            {summary?.gpu_vram?.available
              ? `${formatMetricValue(summary.gpu_vram.memory_used_mib)} / ${formatMetricValue(summary.gpu_vram.memory_total_mib)} MiB`
              : "Unavailable"}
          </strong>
          <span>Current VRAM Load</span>
        </div>
        <div className="benchmark-status-pill">
          <strong>{formatMetricValue(summary?.gpu_vram?.llama_vram_mib, " MiB")}</strong>
          <span>llama.cpp VRAM</span>
        </div>
        <div className={`benchmark-status-pill${swapError ? " benchmark-status-pill-warning" : ""}`}>
          <strong>{formatSeconds(swapDuration)}</strong>
          <span>{summary?.active_benchmark?.status === "swapping" ? "Current Swap" : "Last Swap"}</span>
        </div>
        <div className="benchmark-status-pill">
          <strong>{formatMetricValue(pendingPromptCount)}</strong>
          <span>Pending</span>
        </div>
        <div className="benchmark-status-pill">
          <strong>{formatMetricValue(completedPromptCount)}</strong>
          <span>Completed</span>
        </div>
        <div className="benchmark-status-pill">
          <strong>{formatMetricValue(failedPromptCount)}</strong>
          <span>Failed</span>
        </div>
      </div>
      <LocalLLMSummaryTable summaries={modelSummaries} currentModelId={currentModelId} modelStatusCounts={modelStatusCounts} />
      <div className="client-usage-table-card">
        <div className="client-usage-table-wrap">
          <table className="client-usage-table local-llm-benchmark-table">
            <thead>
              <tr>
                <th>Prompt</th>
                <th>OpenAI Model</th>
                {modelIds.map((modelId, index) => (
                  <th className={modelId === currentModelId ? "local-llm-loaded-column-header" : ""} key={modelId}>
                    {localLlmColumnTitle(modelId, index)}
                    {modelId === currentModelId ? <span className="benchmark-state-badge benchmark-state-badge-loaded">Loaded</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleComparisons.length ? (
                visibleComparisons.map((comparison) => {
                  const resultsByModel = Object.fromEntries(
                    (Array.isArray(comparison.local_results) ? comparison.local_results : []).map((result) => [result.model_id, result])
                  );
                  return (
                  <tr
                    className="benchmark-clickable-row"
                    key={comparison.record_id}
                    onClick={() => setSelectedComparison(comparison)}
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        setSelectedComparison(comparison);
                      }
                    }}
                  >
                    <td>
                      <code>{promptName(comparison)}</code>
                      {comparison.input_snippet ? <span className="muted tiny benchmark-snippet">{comparison.input_snippet}</span> : null}
                    </td>
                    <td>
                      <div className="benchmark-model-cell">
                        <code>{comparison.openai?.model_id || "openai"}</code>
                        <span>{labelSummary({ label: comparison.openai?.label, confidence: comparison.openai?.confidence, outputText: comparison.openai?.output_text })}</span>
                        <span className="muted tiny">Tokens {formatMetricValue(comparison.openai?.usage?.total_tokens)}</span>
                      </div>
                    </td>
                    {modelIds.map((modelId) => (
                      <td key={`${comparison.record_id}-${modelId}`}>
                        <LocalModelCell modelId={modelId} result={resultsByModel[modelId]} />
                      </td>
                    ))}
                  </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={2 + Math.max(modelIds.length, 1)} className="muted">
                    {promptListCleared
                      ? "Prompt list cleared in this view. Score summary is still using the captured benchmark data."
                      : showOnlyDifferences && comparisons.length
                        ? "No label differences in the current benchmark view."
                        : "No OpenAI benchmark records have been captured yet."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      </article>
      <BenchmarkDetailModal
        comparison={selectedComparison}
        modelIds={modelIds}
        onSetCorrectLabel={onSetCorrectLabel ? handleSetCorrectLabel : null}
        correctionChanging={correctionChanging}
        onClose={() => setSelectedComparison(null)}
      />
    </>
  );
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
  localLlmBenchmarkSummary = null,
  onCycleLocalLlmModel,
  cyclingLocalLlmModel = false,
  onRunLoadedLocalLlmModel,
  runningLoadedLocalLlm = false,
  onSetLocalLlmBenchmarkCapture,
  localLlmBenchmarkCaptureChanging = false,
  onSetLocalLlmBenchmarkCorrectLabel,
  localLlmBenchmarkCorrectionChanging = false,
  governanceStatus = null,
  scheduledTasksProps = null,
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
            governanceStatus={governanceStatus}
            className="operational-card-full-span"
          />
        ) : null}

        {currentSection === "benchmarks" ? (
          <LocalLLMBenchmarkTable
            summary={localLlmBenchmarkSummary}
            onCycleModel={onCycleLocalLlmModel}
            cyclingModel={cyclingLocalLlmModel}
            onRunLoadedModel={onRunLoadedLocalLlmModel}
            runningLoadedModel={runningLoadedLocalLlm}
            onSetCaptureEnabled={onSetLocalLlmBenchmarkCapture}
            captureChanging={localLlmBenchmarkCaptureChanging}
            onSetCorrectLabel={onSetLocalLlmBenchmarkCorrectLabel}
            correctionChanging={localLlmBenchmarkCorrectionChanging}
          />
        ) : null}

        {currentSection === "scheduled" ? (
          <ScheduledTasksSection {...(scheduledTasksProps || {})} />
        ) : null}

        {currentSection === "diagnostics" ? (
          <DiagnosticsPage {...diagnosticsProps} className="operational-card-full-span" />
        ) : null}
      </section>
    </OperationalShell>
  );
}
