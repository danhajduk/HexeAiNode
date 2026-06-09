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

function hasVariable(template, name) {
  return variableNames(template).includes(name);
}

function requiredVariable(template, name) {
  return asArray(template?.variables).some((variable) => String(variable?.name || "").trim() === name && Boolean(variable?.required));
}

function variableInputType(variable) {
  const type = String(variable?.type || "").trim().toLowerCase();
  return type === "integer" || type === "number" ? "number" : "text";
}

function isReferenceStrengthVariable(name) {
  return ["face_strength", "body_strength", "body_conditioning_strength", "body_latent_strength"].includes(
    String(name || "").trim()
  );
}

function formatSliderValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "0.00";
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

function seedForPayload(value) {
  const trimmed = String(value || "").trim();
  return trimmed ? trimmed : null;
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

function formatTemplateIntent(value) {
  return String(value || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const DEFAULT_AVATAR_IDENTITY_PROMPT = [
  "same woman as the reference images, preserve exact avatar identity, preserve exact face shape and body proportions, stylized photorealistic digital avatar",
  "youthful adult woman with soft oval heart-shaped face, smooth fair warm skin tone, large almond-shaped vivid green eyes, dark defined lashes, arched dark eyebrows",
  "small straight narrow nose with softly rounded tip, full soft lips with subtle cupid's bow, gentle confident smile, delicate jawline, softly pointed chin, symmetrical attractive face, high cheekbones, smooth cheeks",
  "long thick dark brown to black wavy hair, deep side part slightly off center, voluminous waves falling over shoulders and down the back, glossy dark hair with soft highlights",
  "wearing the same blue glowing headset earpiece with small black microphone boom on the right side of her head, keep headset visible, preserve headset shape and placement",
  "curvy hourglass body shape, fuller bust, narrow waist, rounded hips, soft natural curves, feminine proportions, average height, full thighs, smooth legs, soft arms",
  "preserve the same body mass and silhouette as the full body reference, do not make her skinny, do not make her athletic, do not change her waist-to-hip ratio",
].join(", ");

const DEFAULT_AVATAR_CLOTHING_PROMPT =
  "wearing elegant black lace lingerie, balconette bra with delicate lace cups, thin adjustable shoulder straps, matching high-waisted lace panties, subtle scalloped lace edges, tasteful sensual styling, fitted to her curvy hourglass body";

const DEFAULT_AVATAR_POSE_PROMPT =
  "full body visible from head to feet, standing in a relaxed three-quarter pose, body angled 35 degrees to the right, weight on left leg, right knee softly bent forward, left hand resting on left hip, right arm relaxed along the outer thigh, shoulders relaxed, head turned slightly left toward camera, eyes looking directly at viewer, calm confident expression";

const DEFAULT_AVATAR_QUALITY_PROMPT =
  "transparent background, isolated character cutout, clean alpha edge, studio character reference, sharp face detail, sharp hands, detailed hair strands, consistent identity, consistent body shape, high quality";

function joinPromptSections(sections) {
  return sections.map((section) => String(section || "").trim()).filter(Boolean).join(", ");
}

export function ManualImageGenerationCard({
  payload = null,
  busy = false,
  promptHelperBusy = false,
  visionBusy = false,
  result = null,
  apiBase = "",
  onSubmit,
  onImprovePrompt,
  onUploadReference,
  onDeleteReference,
  onDescribeReference,
  onDeleteOutput,
  onRefresh,
}) {
  const templates = asArray(payload?.templates);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [mode, setMode] = useState("txt2img");
  const [prompt, setPrompt] = useState("");
  const [avatarIdentityPrompt, setAvatarIdentityPrompt] = useState(DEFAULT_AVATAR_IDENTITY_PROMPT);
  const [avatarClothingPrompt, setAvatarClothingPrompt] = useState(DEFAULT_AVATAR_CLOTHING_PROMPT);
  const [avatarPosePrompt, setAvatarPosePrompt] = useState(DEFAULT_AVATAR_POSE_PROMPT);
  const [avatarQualityPrompt, setAvatarQualityPrompt] = useState(DEFAULT_AVATAR_QUALITY_PROMPT);
  const [createLoraMetadata, setCreateLoraMetadata] = useState(false);
  const [negativePrompt, setNegativePrompt] = useState("low quality, blurry, watermark, text");
  const [width, setWidth] = useState("1024");
  const [height, setHeight] = useState("1024");
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("4");
  const [cfg, setCfg] = useState("1.6");
  const [denoise, setDenoise] = useState("0.55");
  const [batchCount, setBatchCount] = useState("1");
  const [randomizeSeed, setRandomizeSeed] = useState(false);
  const [randomizeReferenceStrengths, setRandomizeReferenceStrengths] = useState(false);
  const [referenceStrengthJitter, setReferenceStrengthJitter] = useState("0.05");
  const [templateVariables, setTemplateVariables] = useState({});
  const [referenceFile, setReferenceFile] = useState(null);
  const [selectedReference, setSelectedReference] = useState(null);
  const [faceReference, setFaceReference] = useState(null);
  const [bodyReference, setBodyReference] = useState(null);
  const [sceneReference, setSceneReference] = useState(null);
  const [libraryCategory, setLibraryCategory] = useState("avatar");
  const [libraryRole, setLibraryRole] = useState("reference");
  const [libraryName, setLibraryName] = useState("");
  const [libraryFile, setLibraryFile] = useState(null);
  const [visionMode, setVisionMode] = useState("avatar");
  const [visionPrompt, setVisionPrompt] = useState("");
  const [visionDescription, setVisionDescription] = useState("");
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
  const effectiveTemplate = selectedTemplate;
  const effectiveMode = templateMode(effectiveTemplate) || mode;
  const templateDomain = String(effectiveTemplate?.metadata?.domain || "").trim();
  const templateIntent = formatTemplateIntent(effectiveTemplate?.metadata?.edit_intent);
  const templateReferenceRoles = asArray(effectiveTemplate?.metadata?.reference_roles).join(", ");
  const needsSourceImage = hasVariable(effectiveTemplate, "input_image");
  const needsFaceReference = hasVariable(effectiveTemplate, "face_reference_image");
  const needsBodyReference = hasVariable(effectiveTemplate, "body_reference_image");
  const needsSceneReference = hasVariable(effectiveTemplate, "scene_reference_image");
  const supportsDenoise = hasVariable(effectiveTemplate, "denoise");
  const showAvatarReferences = templateDomain === "avatar" || needsFaceReference || needsBodyReference;
  const showSceneReferences = templateDomain === "scene" || needsSceneReference;
  const showAvatarPromptStructure = templateDomain === "avatar";
  const composedPrompt = showAvatarPromptStructure
    ? joinPromptSections([avatarIdentityPrompt, avatarClothingPrompt, avatarPosePrompt, avatarQualityPrompt])
    : prompt;
  const sourceImageReady = !requiredVariable(effectiveTemplate, "input_image") || Boolean(referenceFile || selectedReference);
  const faceReferenceReady = !requiredVariable(effectiveTemplate, "face_reference_image") || Boolean(faceReference);
  const bodyReferenceReady = !requiredVariable(effectiveTemplate, "body_reference_image") || Boolean(bodyReference);
  const sceneReferenceReady = !requiredVariable(effectiveTemplate, "scene_reference_image") || Boolean(sceneReference);
  const adjustableVariables = asArray(selectedTemplate?.variables).filter((variable) => {
    const name = String(variable?.name || "").trim();
    return (
      name &&
      !isReferenceStrengthVariable(name) &&
      ![
        "positive_prompt",
        "negative_prompt",
        "input_image",
        "face_reference_image",
        "body_reference_image",
        "scene_reference_image",
        "width",
        "height",
        "seed",
        "steps",
        "cfg",
        "denoise",
      ].includes(name)
    );
  });
  const referenceStrengthVariables = asArray(selectedTemplate?.variables).filter((variable) =>
    isReferenceStrengthVariable(String(variable?.name || "").trim())
  );
  const batchCountNumber = Math.min(Math.max(Number.parseInt(batchCount, 10) || 1, 1), 25);
  const canSubmit =
    Boolean(composedPrompt.trim()) &&
    sourceImageReady &&
    faceReferenceReady &&
    bodyReferenceReady &&
    sceneReferenceReady &&
    !busy;
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
      scene_reference_image: sceneReference?.input_image || templateVariables.scene_reference_image || "",
    };
    onSubmit?.({
      template_id: effectiveTemplate?.template_id || null,
      mode: effectiveMode,
      prompt: composedPrompt,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 1024,
      height: Number.parseInt(height, 10) || 1024,
      seed: seedForPayload(seed),
      steps: Number.parseInt(steps, 10) || 4,
      cfg: Number.parseFloat(cfg) || 1.6,
      denoise: Number.parseFloat(denoise) || 0.55,
      batch_count: batchCountNumber,
      randomize_seed: randomizeSeed,
      randomize_reference_strengths: showAvatarReferences && randomizeReferenceStrengths,
      reference_strength_jitter: Number.parseFloat(referenceStrengthJitter) || 0,
      input_image: referenceFile ? null : selectedReference?.input_image || null,
      reference_image_filename: referenceFile?.name || null,
      reference_image_data_base64: referenceData || null,
      template_variables: referenceVariables,
      create_lora_metadata: showAvatarPromptStructure && createLoraMetadata,
    });
  }

  function onReferenceChange(event) {
    const file = event.target.files?.[0] || null;
    setReferenceFile(file);
    if (file) {
      setSelectedReference(null);
    }
    if (file && !needsSourceImage) {
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
      if (libraryRole === "face") {
        setFaceReference(result.reference);
      } else if (libraryRole === "body") {
        setBodyReference(result.reference);
      } else if (libraryCategory === "scene" || libraryRole === "place") {
        setSceneReference(result.reference);
      } else {
        setSelectedReference(result.reference);
        setReferenceFile(null);
        setMode("img2img");
      }
    }
    setLibraryFile(null);
  }

  function useReference(reference, slot = "source") {
    if (slot === "face") {
      setFaceReference(reference);
    } else if (slot === "body") {
      setBodyReference(reference);
    } else if (slot === "scene") {
      setSceneReference(reference);
    } else {
      setSelectedReference(reference);
      setReferenceFile(null);
      setMode("img2img");
      const img2imgTemplate = templateForMode(templates, "img2img");
      if (!needsSourceImage && img2imgTemplate?.template_id && templateMode(selectedTemplate) !== "img2img") {
        setSelectedTemplateId(img2imgTemplate.template_id);
      }
    }
  }

  async function describeReference(reference) {
    const result = await onDescribeReference?.({
      mode: visionMode,
      custom_prompt: visionPrompt,
      reference_relative_path: reference.relative_path,
    });
    if (result?.description) {
      setVisionDescription(String(result.description));
    }
  }

  async function deleteReference(reference) {
    await onDeleteReference?.(reference.relative_path);
    if (selectedReference?.relative_path === reference.relative_path) {
      setSelectedReference(null);
    }
    if (faceReference?.relative_path === reference.relative_path) {
      setFaceReference(null);
    }
    if (bodyReference?.relative_path === reference.relative_path) {
      setBodyReference(null);
    }
    if (sceneReference?.relative_path === reference.relative_path) {
      setSceneReference(null);
    }
  }

  function insertVisionDescription() {
    const description = visionDescription.trim();
    if (!description) {
      return;
    }
    if (showAvatarPromptStructure) {
      setAvatarIdentityPrompt((current) => (current.trim() ? `${current.trim()}, ${description}` : description));
      return;
    }
    setPrompt((current) => (current.trim() ? `${current.trim()}\n${description}` : description));
  }

  function resetTemplateSettings() {
    const defaults = effectiveTemplate?.defaults || {};
    setWidth(String(defaults.width || 1024));
    setHeight(String(defaults.height || 1024));
    setSeed(defaults.seed === null || defaults.seed === undefined ? "" : String(defaults.seed));
    setSteps(String(defaults.steps || 4));
    setCfg(String(defaults.cfg || 1.6));
    setDenoise(String(defaults.denoise || 0.55));
    setNegativePrompt(String(defaults.negative_prompt || "low quality, blurry, watermark, text"));
  }

  async function handleImprovePrompt() {
    if (helperDisabled) {
      return;
    }
    const result = await onImprovePrompt?.({
      template_id: effectiveTemplate?.template_id || null,
      mode: effectiveMode,
      prompt: composedPrompt,
      negative_prompt: negativePrompt,
      width: Number.parseInt(width, 10) || 1024,
      height: Number.parseInt(height, 10) || 1024,
      reference_image_provided: Boolean(referenceFile),
    });
    if (result?.prompt) {
      if (showAvatarPromptStructure) {
        setAvatarQualityPrompt(String(result.prompt));
      } else {
        setPrompt(String(result.prompt));
      }
    }
    if (result?.negative_prompt) {
      setNegativePrompt(String(result.negative_prompt));
    }
  }

  return (
    <>
    <article className="card operational-card-full-span">
      <CardHeader title="Manual Image Generation" subtitle="Prompt-driven ComfyUI generation for the manual session." />
      <div className="manual-generation-status-grid">
        <div className="manual-generation-status-row manual-generation-status-row-primary">
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
        </div>
        <div className="manual-generation-status-row manual-generation-status-row-secondary">
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
    </article>

    <form className="setup-form manual-generation-card-stack operational-card-full-span" onSubmit={handleSubmit}>
      <article className="card manual-generation-card-wide">
        <CardHeader title="Template" subtitle="Select the ComfyUI workflow for this manual job." />
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
            Job Type
            <input type="text" value={effectiveMode} readOnly />
          </label>
        </div>
        <div className="state-grid">
          <span>Description</span>
          <p className="muted tiny manual-generation-template-description">
            {effectiveTemplate?.description || "No template description available."}
          </p>
          <span>Template ID</span>
          <code>{effectiveTemplate?.template_id || "not_configured"}</code>
          <span>Domain</span>
          <code>{templateDomain || "general"}</code>
          <span>Intent</span>
          <code>{templateIntent || effectiveMode}</code>
          <span>Required</span>
          <code>
            {[
              needsSourceImage ? "source" : null,
              needsFaceReference ? "face" : null,
              needsBodyReference ? "body" : null,
              needsSceneReference ? "scene" : null,
            ].filter(Boolean).join(", ") || "prompt"}
          </code>
          <span>Reference Roles</span>
          <code>{templateReferenceRoles || "none"}</code>
          <span>Default Size</span>
          <code>{`${effectiveTemplate?.defaults?.width || 1024} x ${effectiveTemplate?.defaults?.height || 1024}`}</code>
          <span>Current Size</span>
          <code>{`${width || "?"} x ${height || "?"}`}</code>
        </div>
      </article>

      {needsSourceImage ? (
        <article className="card">
          <CardHeader title="Source Image" subtitle="Image used as the direct img2img source for this template." />
          <div className="form-grid two-column-form-grid">
            <label>
              Upload Source
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onReferenceChange} />
            </label>
            <label>
              Selected Source
              <input type="text" value={referenceFile?.name || selectedReference?.name || selectedReference?.filename || ""} readOnly />
            </label>
          </div>
          {references.length ? (
            <div className="image-output-grid">
              {references.slice(0, 8).map((reference) => (
                <div className="image-output-tile" key={`source:${reference.relative_path}`}>
                  <div className="row">
                    <button className="btn" type="button" onClick={() => useReference(reference, "source")} disabled={busy}>
                      Source
                    </button>
                  </div>
                  <a href={`${apiBase}${reference.url}`} target="_blank" rel="noreferrer">
                    <img src={`${apiBase}${reference.url}`} alt={reference.name || reference.filename} />
                    <span>{reference.name || reference.filename}</span>
                  </a>
                  <button className="btn btn-danger" type="button" onClick={() => deleteReference(reference)} disabled={busy}>
                    Delete
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ) : null}

      {showAvatarReferences ? (
        <article className="card">
          <CardHeader title="Avatar References" subtitle="Manage face and body references for avatar templates." />
          <div className="form-grid">
            <label>
              Reference Role
              <select value={libraryRole} onChange={(event) => setLibraryRole(event.target.value)}>
                <option value="face">Face</option>
                <option value="body">Body</option>
                <option value="reference">Reference</option>
              </select>
            </label>
            <label>
              Reference Name
              <input type="text" value={libraryName} onChange={(event) => setLibraryName(event.target.value)} />
            </label>
            <label>
              Upload Avatar Reference
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => {
                  setLibraryCategory("avatar");
                  setLibraryFile(event.target.files?.[0] || null);
                }}
              />
            </label>
          </div>
          <div className="row">
            <button className="btn" type="button" onClick={handleUploadReference} disabled={busy || !libraryFile}>
              Upload Reference
            </button>
            {faceReference ? <code>{`Face: ${faceReference.name || faceReference.filename}`}</code> : null}
            {bodyReference ? <code>{`Body: ${bodyReference.name || bodyReference.filename}`}</code> : null}
          </div>
          {referenceStrengthVariables.length ? (
            <div className="form-grid">
              {referenceStrengthVariables.map((variable) => {
                const name = String(variable?.name || "").trim();
                return (
                  <label className="manual-template-slider" key={name}>
                    <span className="manual-template-slider-heading">
                      <span>{variableLabel(name)}</span>
                      <output>{formatSliderValue(templateVariables[name])}</output>
                    </span>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={templateVariables[name] ?? "0"}
                      onChange={(event) => setTemplateVariables((current) => ({ ...current, [name]: event.target.value }))}
                    />
                  </label>
                );
              })}
            </div>
          ) : null}
          {referenceStrengthVariables.length ? (
            <div className="form-grid">
              <label className="manual-lora-metadata-toggle">
                <input
                  type="checkbox"
                  checked={randomizeReferenceStrengths}
                  onChange={(event) => setRandomizeReferenceStrengths(event.target.checked)}
                />
                Randomize Face/Body
              </label>
              <label>
                Variation
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  max="1"
                  step="0.01"
                  value={referenceStrengthJitter}
                  onChange={(event) => setReferenceStrengthJitter(event.target.value)}
                  disabled={!randomizeReferenceStrengths}
                />
              </label>
            </div>
          ) : null}
          {references.length ? (
            <div className="image-output-grid">
              {references.slice(0, 8).map((reference) => (
                <div className="image-output-tile" key={`avatar:${reference.relative_path}`}>
                  <div className="row">
                    {needsFaceReference ? (
                      <button className="btn" type="button" onClick={() => useReference(reference, "face")} disabled={busy}>
                        Face
                      </button>
                    ) : null}
                    {needsBodyReference ? (
                      <button className="btn" type="button" onClick={() => useReference(reference, "body")} disabled={busy}>
                        Body
                      </button>
                    ) : null}
                  </div>
                  <a href={`${apiBase}${reference.url}`} target="_blank" rel="noreferrer">
                    <img src={`${apiBase}${reference.url}`} alt={reference.name || reference.filename} />
                    <span>{reference.name || reference.filename}</span>
                  </a>
                  <button className="btn btn-danger" type="button" onClick={() => deleteReference(reference)} disabled={busy}>
                    Delete
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ) : null}

      {showSceneReferences ? (
        <article className="card">
          <CardHeader title="Scene Reference" subtitle="Select a place or scene reference for scene templates." />
          <div className="form-grid">
            <label>
              Reference Name
              <input type="text" value={libraryName} onChange={(event) => setLibraryName(event.target.value)} />
            </label>
            <label>
              Upload Scene Reference
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => {
                  setLibraryCategory("scene");
                  setLibraryRole("place");
                  setLibraryFile(event.target.files?.[0] || null);
                }}
              />
            </label>
          </div>
          <div className="row">
            <button className="btn" type="button" onClick={handleUploadReference} disabled={busy || !libraryFile}>
              Upload Reference
            </button>
            {sceneReference ? <code>{`Scene: ${sceneReference.name || sceneReference.filename}`}</code> : null}
          </div>
          {references.length ? (
            <div className="image-output-grid">
              {references.slice(0, 8).map((reference) => (
                <div className="image-output-tile" key={`scene:${reference.relative_path}`}>
                  <div className="row">
                    <button className="btn" type="button" onClick={() => useReference(reference, "scene")} disabled={busy}>
                      Scene
                    </button>
                  </div>
                  <a href={`${apiBase}${reference.url}`} target="_blank" rel="noreferrer">
                    <img src={`${apiBase}${reference.url}`} alt={reference.name || reference.filename} />
                    <span>{reference.name || reference.filename}</span>
                  </a>
                  <button className="btn btn-danger" type="button" onClick={() => deleteReference(reference)} disabled={busy}>
                    Delete
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ) : null}

      <article className="card manual-generation-card-wide">
        <CardHeader title="Vision" subtitle="Describe reference images with the local vision runtime." />
        <div className="form-grid two-column-form-grid">
          <label>
            Vision Mode
            <select value={visionMode} onChange={(event) => setVisionMode(event.target.value)}>
              <option value="avatar">Avatar</option>
              <option value="scene">Scene / Place</option>
              <option value="image">Image</option>
            </select>
          </label>
          <label>
            Vision Prompt
            <input type="text" value={visionPrompt} onChange={(event) => setVisionPrompt(event.target.value)} />
          </label>
        </div>
        {references.length ? (
          <div className="image-output-grid">
            {references.slice(0, 8).map((reference) => (
              <div className="image-output-tile" key={`vision:${reference.relative_path}`}>
                <div className="row">
                  <button className="btn" type="button" onClick={() => describeReference(reference)} disabled={visionBusy}>
                    {visionBusy ? "Describing..." : "Describe"}
                  </button>
                </div>
                <a href={`${apiBase}${reference.url}`} target="_blank" rel="noreferrer">
                  <img src={`${apiBase}${reference.url}`} alt={reference.name || reference.filename} />
                  <span>{reference.name || reference.filename}</span>
                </a>
                <button className="btn btn-danger" type="button" onClick={() => deleteReference(reference)} disabled={busy}>
                  Delete
                </button>
              </div>
            ))}
          </div>
        ) : null}
        {visionDescription ? (
          <div className="setup-form">
            <label>
              Vision Description
              <textarea rows={3} value={visionDescription} onChange={(event) => setVisionDescription(event.target.value)} />
            </label>
            <div className="row">
              <button className="btn" type="button" onClick={insertVisionDescription}>
                Insert Description
              </button>
            </div>
          </div>
        ) : null}
      </article>

      <article className="card manual-generation-card-wide">
        <CardHeader title="Prompt" subtitle="Prompt text and template settings for the selected workflow." />
        {showAvatarPromptStructure ? (
          <div className="manual-avatar-prompt-grid">
            <label>
              Identity / Body
              <textarea rows={7} value={avatarIdentityPrompt} onChange={(event) => setAvatarIdentityPrompt(event.target.value)} />
            </label>
            <label>
              Clothing
              <textarea rows={4} value={avatarClothingPrompt} onChange={(event) => setAvatarClothingPrompt(event.target.value)} />
            </label>
            <label>
              Pose
              <textarea rows={4} value={avatarPosePrompt} onChange={(event) => setAvatarPosePrompt(event.target.value)} />
            </label>
            <label>
              Background / Quality
              <textarea rows={4} value={avatarQualityPrompt} onChange={(event) => setAvatarQualityPrompt(event.target.value)} />
            </label>
            <label className="manual-avatar-compiled-prompt">
              Compiled Prompt
              <textarea rows={5} value={composedPrompt} readOnly />
            </label>
          </div>
        ) : (
          <label>
            Prompt
            <textarea rows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </label>
        )}
        <div className="row">
          <button className="btn" type="button" onClick={handleImprovePrompt} disabled={helperDisabled}>
            {promptHelperBusy ? "Drafting..." : "Draft / Improve Prompt"}
          </button>
          <button className="btn" type="button" onClick={resetTemplateSettings} disabled={busy}>
            Reset Template Settings
          </button>
          {showAvatarPromptStructure ? (
            <label className="manual-lora-metadata-toggle">
              <input
                type="checkbox"
                checked={createLoraMetadata}
                onChange={(event) => setCreateLoraMetadata(event.target.checked)}
              />
              Create LoRA metadata
            </label>
          ) : null}
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
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={seed}
              onChange={(event) => setSeed(event.target.value.replace(/\D/g, ""))}
            />
          </label>
          <label>
            Images to Queue
            <input
              type="number"
              min="1"
              max="25"
              step="1"
              value={batchCount}
              onChange={(event) => setBatchCount(event.target.value)}
            />
          </label>
          <label className="manual-lora-metadata-toggle">
            <input
              type="checkbox"
              checked={randomizeSeed}
              onChange={(event) => setRandomizeSeed(event.target.checked)}
            />
            Randomize Seed
          </label>
          <label>
            Steps
            <input type="number" min="1" max="50" value={steps} onChange={(event) => setSteps(event.target.value)} />
          </label>
          <label>
            CFG
            <input type="number" min="0" step="0.1" value={cfg} onChange={(event) => setCfg(event.target.value)} />
          </label>
          {supportsDenoise ? (
            <label>
              Denoise
              <input
                type="number"
                inputMode="decimal"
                min="0"
                max="1"
                step="0.01"
                value={denoise}
                onChange={(event) => setDenoise(event.target.value)}
              />
            </label>
          ) : null}
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
            {busy ? "Generating..." : batchCountNumber > 1 ? `Queue ${batchCountNumber} Images` : "Generate"}
          </button>
          <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
            Refresh Outputs
          </button>
        </div>
      </article>
    </form>

    <article className="card operational-card-full-span">
      <CardHeader title="Outputs" subtitle="Recent manual ComfyUI results stored in the manual output folder." />
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
    </>
  );
}
