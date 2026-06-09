import { useEffect, useMemo, useState } from "react";

import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      resolve("");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("file_read_failed"));
    reader.readAsDataURL(file);
  });
}

function serviceState(value) {
  if (value && typeof value === "object") {
    return value.state || "unknown";
  }
  return value || "unknown";
}

function variableNames(template) {
  return asArray(template?.variables).map((variable) => String(variable?.name || "").trim()).filter(Boolean);
}

function templateMode(template) {
  const metadataMode = String(template?.metadata?.input_mode || "").trim();
  if (metadataMode === "image") {
    return "img2img";
  }
  if (variableNames(template).includes("input_image")) {
    return "img2img";
  }
  return "txt2img";
}

function templateForMode(templates, mode) {
  const normalizedMode = String(mode || "").trim();
  return asArray(templates).find((template) => templateMode(template) === normalizedMode) || null;
}

function variableInputType(variable) {
  const type = String(variable?.type || "").trim().toLowerCase();
  return type === "integer" || type === "number" ? "number" : "text";
}

function variableLabel(name) {
  return String(name || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function objectValue(value) {
  return value && typeof value === "object" ? value : {};
}

function formatQueue(session) {
  if (session.queue_available === false) {
    return "unavailable";
  }
  const running = Number(session.running_count || 0);
  const pending = Number(session.pending_count || 0);
  if (!running && !pending) {
    return "idle";
  }
  return `${running} running / ${pending} pending`;
}

function formatProgress(progress) {
  if (Number.isFinite(Number(progress.percent))) {
    return `${Number(progress.percent).toFixed(1)}%`;
  }
  if (progress.value !== null && progress.value !== undefined && progress.max !== null && progress.max !== undefined) {
    return `${progress.value}/${progress.max}`;
  }
  if (progress.fallback_status) {
    return progress.fallback_status;
  }
  if (progress.available === false) {
    return "unavailable";
  }
  return progress.active ? "working" : "idle";
}

function formatLatestJob(job) {
  const status = String(job?.status || "").trim();
  return status || "none";
}

export function ManualImageGenerationCard({
  payload = null,
  busy = false,
  promptHelperBusy = false,
  result = null,
  apiBase = "",
  onSubmit,
  onImprovePrompt,
  onUploadReference,
  onDeleteOutput,
  onRefresh,
}) {
  const templates = asArray(payload?.templates);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [mode, setMode] = useState("txt2img");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("low quality, blurry, watermark, text");
  const [width, setWidth] = useState("1024");
  const [height, setHeight] = useState("1024");
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("4");
  const [cfg, setCfg] = useState("1.6");
  const [denoise, setDenoise] = useState("0.55");
  const [templateVariables, setTemplateVariables] = useState({});
  const [referenceFile, setReferenceFile] = useState(null);
  const [selectedReference, setSelectedReference] = useState(null);
  const [faceReference, setFaceReference] = useState(null);
  const [bodyReference, setBodyReference] = useState(null);
  const [libraryCategory, setLibraryCategory] = useState("avatar");
  const [libraryRole, setLibraryRole] = useState("reference");
  const [libraryName, setLibraryName] = useState("");
  const [libraryFile, setLibraryFile] = useState(null);
  const outputs = asArray(payload?.outputs);
  const references = asArray(payload?.references);
  const service = payload?.service || {};
  const runtimeService = objectValue(payload?.runtime_service);
  const generationStatus = objectValue(payload?.generation_status);
  const generationSession = objectValue(generationStatus.session || service.session);
  const generationProgress = objectValue(generationStatus.progress);
  const latestJob = objectValue(payload?.latest_job);
  const displayedLatestJob = latestJob.prompt_id || latestJob.status ? latestJob : objectValue(result);
  const latestJobProgress = objectValue(displayedLatestJob.progress);
  const latestJobStatus = formatLatestJob(displayedLatestJob);
  const statusProgress =
    generationProgress.available === false && latestJobProgress.available !== false ? latestJobProgress : generationProgress;
  const progressActive =
    busy ||
    Boolean(generationSession.queue_active) ||
    ["submitted", "queued", "running"].includes(latestJobStatus);
  const effectiveProgress = {
    ...statusProgress,
    active: Boolean(statusProgress.active) || progressActive,
    fallback_status:
      Number.isFinite(Number(statusProgress.percent)) || (statusProgress.value !== null && statusProgress.value !== undefined)
        ? null
        : progressActive
          ? latestJobStatus === "none"
            ? "working"
            : latestJobStatus
          : latestJobStatus === "completed"
            ? "completed"
            : null,
  };
  const manualPaths = payload?.manual_paths || {};
  const progressPercent = Number(effectiveProgress.percent);
  const displayedProgressPercent = Number.isFinite(progressPercent) ? progressPercent : latestJobStatus === "completed" ? 100 : null;
  const selectedTemplate = useMemo(
    () => templates.find((template) => template?.template_id === selectedTemplateId) || templates[0] || null,
    [templates, selectedTemplateId]
  );
  const effectiveMode = referenceFile || selectedReference ? "img2img" : mode;
  const effectiveTemplate =
    selectedTemplate && templateMode(selectedTemplate) === effectiveMode
      ? selectedTemplate
      : templateForMode(templates, effectiveMode) || selectedTemplate;
  const adjustableVariables = asArray(selectedTemplate?.variables).filter((variable) => {
    const name = String(variable?.name || "").trim();
    return (
      name &&
      ![
        "positive_prompt",
        "negative_prompt",
        "input_image",
        "face_reference_image",
        "body_reference_image",
        "width",
        "height",
        "seed",
        "steps",
        "cfg",
        "denoise",
      ].includes(name)
    );
  });
  const canSubmit = Boolean(prompt.trim()) && !busy;
  const helperDisabled = busy || promptHelperBusy;

  useEffect(() => {
    if (!selectedTemplateId && templates[0]?.template_id) {
      setSelectedTemplateId(templates[0].template_id);
    }
  }, [selectedTemplateId, templates]);

  useEffect(() => {
    if (!selectedTemplate) {
      return;
    }
    const defaults = selectedTemplate.defaults || {};
    setMode(templateMode(selectedTemplate));
    setNegativePrompt(String(defaults.negative_prompt || "low quality, blurry, watermark, text"));
    setWidth(String(defaults.width || 1024));
    setHeight(String(defaults.height || 1024));
    setSeed(defaults.seed === null || defaults.seed === undefined ? "" : String(defaults.seed));
    setSteps(String(defaults.steps || 4));
    setCfg(String(defaults.cfg || 1.6));
    setDenoise(String(defaults.denoise || 0.55));
    setTemplateVariables(
      Object.fromEntries(
        adjustableVariables.map((variable) => {
          const name = String(variable?.name || "").trim();
          const value = defaults[name] ?? variable?.default ?? "";
          return [name, value === null || value === undefined ? "" : String(value)];
        })
      )
    );
  }, [selectedTemplateId]);

  async function handleSubmit(event) {
    event.preventDefault();
    const referenceData = referenceFile ? await fileToDataUrl(referenceFile) : "";
    const referenceVariables = {
      ...templateVariables,
      face_reference_image: faceReference?.input_image || templateVariables.face_reference_image || "",
      body_reference_image: bodyReference?.input_image || templateVariables.body_reference_image || "",
    };
    onSubmit?.({
      template_id: effectiveTemplate?.template_id || null,
      mode: effectiveMode,
      prompt,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 1024,
      height: Number.parseInt(height, 10) || 1024,
      seed: seed === "" ? null : Number.parseInt(seed, 10),
      steps: Number.parseInt(steps, 10) || 4,
      cfg: Number.parseFloat(cfg) || 1.6,
      denoise: Number.parseFloat(denoise) || 0.55,
      input_image: referenceFile ? null : selectedReference?.input_image || null,
      reference_image_filename: referenceFile?.name || null,
      reference_image_data_base64: referenceData || null,
      template_variables: referenceVariables,
    });
  }

  function onReferenceChange(event) {
    const file = event.target.files?.[0] || null;
    setReferenceFile(file);
    if (file) {
      setSelectedReference(null);
    }
    if (file) {
      setMode("img2img");
      const img2imgTemplate = templateForMode(templates, "img2img");
      if (img2imgTemplate?.template_id && templateMode(selectedTemplate) !== "img2img") {
        setSelectedTemplateId(img2imgTemplate.template_id);
      }
    }
  }

  async function handleUploadReference() {
    if (!libraryFile || busy) {
      return;
    }
    const referenceData = await fileToDataUrl(libraryFile);
    const result = await onUploadReference?.({
      category: libraryCategory,
      role: libraryRole,
      name: libraryName || libraryFile.name,
      filename: libraryFile.name,
      data_base64: referenceData,
    });
    if (result?.reference) {
      setSelectedReference(result.reference);
      setReferenceFile(null);
      setMode("img2img");
    }
    setLibraryFile(null);
  }

  function useReference(reference, slot = "source") {
    if (slot === "face") {
      setFaceReference(reference);
    } else if (slot === "body") {
      setBodyReference(reference);
    } else {
      setSelectedReference(reference);
      setReferenceFile(null);
      setMode("img2img");
      const img2imgTemplate = templateForMode(templates, "img2img");
      if (img2imgTemplate?.template_id && templateMode(selectedTemplate) !== "img2img") {
        setSelectedTemplateId(img2imgTemplate.template_id);
      }
    }
  }

  async function handleImprovePrompt() {
    if (helperDisabled) {
      return;
    }
    const result = await onImprovePrompt?.({
      template_id: effectiveTemplate?.template_id || null,
      mode: effectiveMode,
      prompt,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 1024,
      height: Number.parseInt(height, 10) || 1024,
      reference_image_provided: Boolean(referenceFile),
    });
    if (result?.prompt) {
      setPrompt(String(result.prompt));
    }
    if (result?.negative_prompt) {
      setNegativePrompt(String(result.negative_prompt));
    }
  }

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Manual Image Generation" subtitle="Prompt-driven ComfyUI generation for the manual session." />
      <div className="manual-generation-status-grid">
        <div className="manual-generation-status-item">
          <span>ComfyUI Runtime</span>
          <StatusBadge value={serviceState(runtimeService)} />
        </div>
        <div className="manual-generation-status-item">
          <span>ComfyUI Web UI</span>
          <StatusBadge value={serviceState(service)} />
        </div>
        <div className="manual-generation-status-item">
          <span>Manual Session</span>
          <StatusBadge value={generationSession.state || (service.manual_session_active ? "active" : "inactive")} />
        </div>
        <div className="manual-generation-status-item">
          <span>Queue</span>
          <code>{formatQueue(generationSession)}</code>
        </div>
        <div className="manual-generation-status-item">
          <span>Latest Job</span>
          <StatusBadge value={busy ? "submitting" : latestJobStatus} />
        </div>
        <div className="manual-generation-status-item">
          <span>Current Prompt</span>
          <code>{effectiveProgress.prompt_id || generationSession.running_prompt_id || displayedLatestJob.prompt_id || "none"}</code>
        </div>
        <div className="manual-generation-status-item">
          <span>Output</span>
          <code>{manualPaths.output_dir || "not_configured"}</code>
        </div>
        <div className="manual-generation-status-item">
          <span>Last Submit</span>
          <code>{displayedLatestJob.prompt_id || "none"}</code>
        </div>
        <div className="manual-generation-status-item">
          <span>Template</span>
          <code>{effectiveTemplate?.template_id || "not_configured"}</code>
        </div>
      </div>
      <div className="manual-generation-progress-panel">
        <div className="manual-generation-progress-heading">
          <span>Progress</span>
          <code>{formatProgress(effectiveProgress)}</code>
        </div>
        <div
          className={`manual-generation-progress-track ${progressActive && displayedProgressPercent === null ? "is-active" : ""}`}
          aria-hidden="true"
        >
          <span
            style={{
              width:
                displayedProgressPercent !== null
                  ? `${Math.max(Math.min(displayedProgressPercent, 100), 0)}%`
                  : undefined,
            }}
          />
        </div>
      </div>
      <form className="setup-form" onSubmit={handleSubmit}>
        <div className="form-grid two-column-form-grid">
          <label>
            Template
            <select value={selectedTemplate?.template_id || ""} onChange={(event) => setSelectedTemplateId(event.target.value)}>
              {templates.map((template) => (
                <option value={template?.template_id} key={template?.template_id}>
                  {template?.template_name || template?.template_id}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reference Image
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onReferenceChange} />
          </label>
        </div>
        <div className="form-grid">
          <label>
            Reference Type
            <select value={libraryCategory} onChange={(event) => setLibraryCategory(event.target.value)}>
              <option value="avatar">Avatar</option>
              <option value="scene">Scene / Place</option>
            </select>
          </label>
          <label>
            Reference Role
            <select value={libraryRole} onChange={(event) => setLibraryRole(event.target.value)}>
              <option value="reference">Reference</option>
              <option value="face">Face</option>
              <option value="body">Body</option>
              <option value="place">Place</option>
            </select>
          </label>
          <label>
            Reference Name
            <input type="text" value={libraryName} onChange={(event) => setLibraryName(event.target.value)} />
          </label>
          <label>
            Upload Reference
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setLibraryFile(event.target.files?.[0] || null)} />
          </label>
        </div>
        <div className="row">
          <button className="btn" type="button" onClick={handleUploadReference} disabled={busy || !libraryFile}>
            Upload Reference
          </button>
          {selectedReference ? <code>{selectedReference.name || selectedReference.filename}</code> : null}
          {faceReference ? <code>{`Face: ${faceReference.name || faceReference.filename}`}</code> : null}
          {bodyReference ? <code>{`Body: ${bodyReference.name || bodyReference.filename}`}</code> : null}
        </div>
        {references.length ? (
          <div className="image-output-grid">
            {references.slice(0, 8).map((reference) => (
              <div className="image-output-tile" key={reference.relative_path}>
                <div className="row">
                  <button className="btn" type="button" onClick={() => useReference(reference, "source")} disabled={busy}>
                    Source
                  </button>
                  <button className="btn" type="button" onClick={() => useReference(reference, "face")} disabled={busy}>
                    Face
                  </button>
                  <button className="btn" type="button" onClick={() => useReference(reference, "body")} disabled={busy}>
                    Body
                  </button>
                </div>
                <a href={`${apiBase}${reference.url}`} target="_blank" rel="noreferrer">
                  <img src={`${apiBase}${reference.url}`} alt={reference.name || reference.filename} />
                  <span>{reference.name || reference.filename}</span>
                </a>
              </div>
            ))}
          </div>
        ) : null}
        <label>
          Prompt
          <textarea rows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>
        <div className="row">
          <button className="btn" type="button" onClick={handleImprovePrompt} disabled={helperDisabled}>
            {promptHelperBusy ? "Drafting..." : "Draft / Improve Prompt"}
          </button>
        </div>
        <label>
          Negative Prompt
          <textarea rows={2} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} />
        </label>
        <div className="form-grid">
          <label>
            Width
            <input type="number" min="256" step="8" value={width} onChange={(event) => setWidth(event.target.value)} />
          </label>
          <label>
            Height
            <input type="number" min="256" step="8" value={height} onChange={(event) => setHeight(event.target.value)} />
          </label>
          <label>
            Seed
            <input type="number" value={seed} onChange={(event) => setSeed(event.target.value)} />
          </label>
          <label>
            Steps
            <input type="number" min="1" max="50" value={steps} onChange={(event) => setSteps(event.target.value)} />
          </label>
          <label>
            CFG
            <input type="number" min="0" step="0.1" value={cfg} onChange={(event) => setCfg(event.target.value)} />
          </label>
          <label>
            Denoise
            <input type="number" min="0" max="1" step="0.05" value={denoise} onChange={(event) => setDenoise(event.target.value)} />
          </label>
        </div>
        {adjustableVariables.length ? (
          <div className="form-grid">
            {adjustableVariables.map((variable) => {
              const name = String(variable?.name || "").trim();
              return (
                <label key={name}>
                  {variableLabel(name)}
                  <input
                    type={variableInputType(variable)}
                    value={templateVariables[name] ?? ""}
                    onChange={(event) => setTemplateVariables((current) => ({ ...current, [name]: event.target.value }))}
                  />
                </label>
              );
            })}
          </div>
        ) : null}
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={!canSubmit}>
            {busy ? "Generating..." : "Generate"}
          </button>
          <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
            Refresh Outputs
          </button>
        </div>
      </form>
      {outputs.length ? (
        <div className="image-output-grid">
          {outputs.map((output) => (
            <div className="image-output-tile" key={output.relative_path}>
              <a href={`${apiBase}${output.url}`} target="_blank" rel="noreferrer">
                <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                <span>{output.filename || output.relative_path}</span>
              </a>
              <button className="btn btn-danger" type="button" onClick={() => onDeleteOutput?.(output.relative_path)} disabled={busy}>
                Delete
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted tiny">No manual outputs.</p>
      )}
    </article>
  );
}
