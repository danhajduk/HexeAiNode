import { useState } from "react";

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

export function ManualImageGenerationCard({
  payload = null,
  busy = false,
  result = null,
  apiBase = "",
  onSubmit,
  onRefresh,
}) {
  const [mode, setMode] = useState("txt2img");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("low quality, blurry, watermark, text");
  const [width, setWidth] = useState("1024");
  const [height, setHeight] = useState("1024");
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("4");
  const [cfg, setCfg] = useState("1.6");
  const [denoise, setDenoise] = useState("0.55");
  const [referenceFile, setReferenceFile] = useState(null);
  const outputs = asArray(payload?.outputs);
  const service = payload?.service || {};
  const manualPaths = payload?.manual_paths || {};
  const canSubmit = Boolean(prompt.trim()) && !busy;

  async function handleSubmit(event) {
    event.preventDefault();
    const referenceData = referenceFile ? await fileToDataUrl(referenceFile) : "";
    onSubmit?.({
      mode: referenceFile ? "img2img" : mode,
      prompt,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 1024,
      height: Number.parseInt(height, 10) || 1024,
      seed: seed === "" ? null : Number.parseInt(seed, 10),
      steps: Number.parseInt(steps, 10) || 4,
      cfg: Number.parseFloat(cfg) || 1.6,
      denoise: Number.parseFloat(denoise) || 0.55,
      reference_image_filename: referenceFile?.name || null,
      reference_image_data_base64: referenceData || null,
    });
  }

  function onReferenceChange(event) {
    const file = event.target.files?.[0] || null;
    setReferenceFile(file);
    if (file) {
      setMode("img2img");
    }
  }

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Manual Image Generation" subtitle="Prompt-driven ComfyUI generation for the manual session." />
      <div className="state-grid">
        <span>ComfyUI Web UI</span>
        <StatusBadge value={serviceState(service)} />
        <span>Output</span>
        <code>{manualPaths.output_dir || "not_configured"}</code>
        <span>Last Submit</span>
        <code>{result?.prompt_id || "none"}</code>
        <span>Template</span>
        <code>{referenceFile || mode === "img2img" ? "template.img2img.realvisxl.v1" : "template.txt2img.realvisxl.v1"}</code>
      </div>
      <form className="setup-form" onSubmit={handleSubmit}>
        <div className="form-grid two-column-form-grid">
          <label>
            Mode
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="txt2img">Text</option>
              <option value="img2img">Image</option>
            </select>
          </label>
          <label>
            Reference Image
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onReferenceChange} />
          </label>
        </div>
        <label>
          Prompt
          <textarea rows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>
        <label>
          Negative Prompt
          <textarea rows={2} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} />
        </label>
        <div className="form-grid">
          <label>
            Width
            <input type="number" min="256" step="64" value={width} onChange={(event) => setWidth(event.target.value)} />
          </label>
          <label>
            Height
            <input type="number" min="256" step="64" value={height} onChange={(event) => setHeight(event.target.value)} />
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
            <a
              className="image-output-tile"
              href={`${apiBase}${output.url}`}
              target="_blank"
              rel="noreferrer"
              key={output.relative_path}
            >
              <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
              <span>{output.filename || output.relative_path}</span>
            </a>
          ))}
        </div>
      ) : (
        <p className="muted tiny">No manual outputs.</p>
      )}
    </article>
  );
}
