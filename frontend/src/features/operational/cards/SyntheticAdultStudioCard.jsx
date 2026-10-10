import { useEffect, useMemo, useState } from "react";

import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

const TEMPLATE_ID = "template.synthetic_adult_body_reference.realvisxl.v1";
const DEFAULT_NEGATIVE =
  "child, teen, underage, youthful, changed identity, different body shape, cropped head, cropped body, missing legs, missing feet, distorted anatomy, extra limbs, malformed hands, blurry, low quality, watermark, text";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("reference_read_failed"));
    reader.readAsDataURL(file);
  });
}

function outputUrl(apiBase, output) {
  const direct = String(output?.url || "").trim();
  if (direct) {
    return direct.startsWith("http") ? direct : `${apiBase}${direct}`;
  }
  const relative = String(output?.relative_path || "").trim();
  return relative ? `${apiBase}/api/manual-image-generation/outputs/${relative.split("/").map(encodeURIComponent).join("/")}` : "";
}

export function SyntheticAdultStudioCard({ payload = null, busy = false, result = null, apiBase = "", onUploadReference, onSubmit, onRefresh }) {
  const [referenceFile, setReferenceFile] = useState(null);
  const [reference, setReference] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState(DEFAULT_NEGATIVE);
  const [width, setWidth] = useState("768");
  const [height, setHeight] = useState("1152");
  const [batchCount, setBatchCount] = useState("4");
  const [seed, setSeed] = useState("");
  const [identityStrength, setIdentityStrength] = useState("0.82");
  const [bodyStrength, setBodyStrength] = useState("0.72");
  const [confirmedAdult, setConfirmedAdult] = useState(false);
  const [localStatus, setLocalStatus] = useState("");

  const templateAvailable = asArray(payload?.templates).some((template) => template?.template_id === TEMPLATE_ID);
  const outputs = asArray(payload?.outputs).slice(0, 12);
  const latestJob = payload?.latest_job || result || {};
  const canSubmit = templateAvailable && confirmedAdult && Boolean(referenceFile || reference) && Boolean(prompt.trim()) && !busy;

  useEffect(() => {
    if (!referenceFile) {
      setPreviewUrl("");
      return undefined;
    }
    const nextUrl = URL.createObjectURL(referenceFile);
    setPreviewUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [referenceFile]);

  const referencePreview = useMemo(() => previewUrl || outputUrl(apiBase, reference), [apiBase, previewUrl, reference]);

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setLocalStatus("uploading_reference");
    let selectedReference = reference;
    if (referenceFile) {
      const upload = await onUploadReference?.({
        category: "avatar",
        role: "body",
        name: referenceFile.name.replace(/\.[^.]+$/, ""),
        filename: referenceFile.name,
        data_base64: await fileToDataUrl(referenceFile),
      });
      selectedReference = upload?.reference || null;
      if (!selectedReference?.input_image) {
        setLocalStatus("reference_upload_failed");
        return;
      }
      setReference(selectedReference);
      setReferenceFile(null);
    }
    setLocalStatus("submitting");
    const numericSeed = String(seed).trim() ? Number.parseInt(seed, 10) : null;
    const submission = await onSubmit?.({
      template_id: TEMPLATE_ID,
      mode: "txt2img",
      prompt: `adult synthetic avatar, age 25 or older, ${prompt.trim()}`,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 768,
      height: Number.parseInt(height, 10) || 1152,
      seed: Number.isFinite(numericSeed) ? numericSeed : null,
      steps: 4,
      cfg: 1.2,
      denoise: 1,
      batch_count: Math.min(Math.max(Number.parseInt(batchCount, 10) || 1, 1), 12),
      randomize_seed: !Number.isFinite(numericSeed),
      randomize_reference_strengths: false,
      template_variables: {
        avatar_name: "synthetic_adult",
        face_reference_image: selectedReference.input_image,
        body_reference_image: selectedReference.input_image,
        face_strength: Number.parseFloat(identityStrength) || 0.82,
        body_depth_strength: Number.parseFloat(bodyStrength) || 0.72,
      },
    });
    setLocalStatus(submission ? "submitted" : "submission_failed");
  }

  return (
    <article className="card synthetic-adult-studio-card">
      <CardHeader title="Synthetic Adult Studio" subtitle="Create local, body-guided images of an adult AI avatar for adult-profile publishing." />

      <form className="setup-form" onSubmit={submit}>
        <div className="state-grid compact-grid">
          <span>Runtime</span><StatusBadge value="comfyui_gpu" />
          <span>Workflow</span><StatusBadge value={templateAvailable ? "ready" : "missing"} />
          <span>Latest Job</span><StatusBadge value={latestJob.status || localStatus || "idle"} />
        </div>

        <section className="avatar-reference-upload-panel">
          <h3>1. Body reference</h3>
          <p className="muted tiny">Use only a fully synthetic avatar that clearly represents an adult. The same image guides facial identity, proportions, and pose silhouette.</p>
          <label className="avatar-upload-control">
            <span className="btn btn-primary">Choose Body Reference</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { setReferenceFile(event.target.files?.[0] || null); setReference(null); }} />
          </label>
          {referencePreview ? <img className="synthetic-adult-reference-preview" src={referencePreview} alt="Selected synthetic adult avatar reference" /> : null}
        </section>

        <section>
          <h3>2. Describe the image</h3>
          <label>
            Prompt
            <textarea rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Setting, outfit, pose, lighting, camera framing, mood, and aesthetic…" />
          </label>
          <label>
            Negative prompt
            <textarea rows={4} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} />
          </label>
        </section>

        <section>
          <h3>3. Generation controls</h3>
          <div className="form-grid two-column-form-grid">
            <label>Width<input type="number" min="512" max="1536" step="64" value={width} onChange={(event) => setWidth(event.target.value)} /></label>
            <label>Height<input type="number" min="512" max="1536" step="64" value={height} onChange={(event) => setHeight(event.target.value)} /></label>
            <label>Images<input type="number" min="1" max="12" value={batchCount} onChange={(event) => setBatchCount(event.target.value)} /></label>
            <label>Seed (blank = random)<input type="number" value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
            <label>Identity strength<input type="number" min="0" max="1" step="0.05" value={identityStrength} onChange={(event) => setIdentityStrength(event.target.value)} /></label>
            <label>Body/pose strength<input type="number" min="0" max="1" step="0.05" value={bodyStrength} onChange={(event) => setBodyStrength(event.target.value)} /></label>
          </div>
          <label className="manual-lora-metadata-toggle">
            <input type="checkbox" checked={confirmedAdult} onChange={(event) => setConfirmedAdult(event.target.checked)} />
            I confirm this is a fully synthetic avatar represented as age 25+ and that no real person or minor is depicted.
          </label>
        </section>

        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={!canSubmit}>{busy ? "Working…" : "Generate Images"}</button>
          <button className="btn" type="button" onClick={onRefresh} disabled={busy}>Refresh</button>
          {localStatus ? <StatusBadge value={localStatus} /> : null}
        </div>
      </form>

      {outputs.length ? (
        <section>
          <h3>Recent outputs</h3>
          <div className="avatar-reference-card-grid">
            {outputs.map((output) => {
              const url = outputUrl(apiBase, output);
              return url ? <a href={url} target="_blank" rel="noreferrer" key={output.relative_path || url}><img src={url} alt="Generated synthetic adult avatar" /></a> : null;
            })}
          </div>
        </section>
      ) : null}
    </article>
  );
}
