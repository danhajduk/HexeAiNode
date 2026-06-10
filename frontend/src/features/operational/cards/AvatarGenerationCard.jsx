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

function profileImageUrl(apiBase, url) {
  const normalized = String(url || "").trim();
  if (!normalized) {
    return "";
  }
  return `${apiBase || ""}${normalized}`;
}

function profileName(profile) {
  return profile?.name || profile?.profile_id || "avatar";
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function hasExtraction(profile) {
  return Boolean(profile?.extraction?.structured && typeof profile.extraction.structured === "object");
}

function splitTerms(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean);
  }
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formattedJson(value) {
  return JSON.stringify(objectValue(value), null, 2);
}

function selectedFileNames(files) {
  return asArray(files).map((file) => file?.name).filter(Boolean).join(", ") || "none";
}

function profileReferences(profile, role) {
  return asArray(objectValue(profile?.references)[role]);
}

function bodyDepthProfile(profile) {
  return objectValue(profile?.body_depth_profile);
}

function faceProfile(profile) {
  return objectValue(profile?.face_profile);
}

function rawBodyReferences(profile) {
  return profileReferences(profile, "body_depth").filter((reference) => !reference?.background_removed);
}

function noBgBodyReferences(profile) {
  return profileReferences(profile, "body_depth").filter((reference) => Boolean(reference?.background_removed));
}

function extractionEditorState(profile) {
  const extraction = objectValue(profile?.extraction);
  const structured = objectValue(extraction.structured);
  const promptSections = objectValue(structured.prompt_sections);
  const bodyProfile = objectValue(structured.body_profile);
  const permanentIdentity = objectValue(structured.permanent_identity);
  return {
    face_description: String(extraction.face_description || ""),
    body_description: String(extraction.body_description || ""),
    identity: String(promptSections.identity || structured.identity_prompt || permanentIdentity.identity_prompt || ""),
    face: String(promptSections.face || ""),
    hair: String(promptSections.hair || ""),
    body_shape: String(promptSections.body_shape || bodyProfile.body_prompt || ""),
    pose: String(promptSections.pose || ""),
    clothing: String(promptSections.clothing || ""),
    accessories: String(promptSections.accessories || ""),
    preservation: String(promptSections.preservation || ""),
    negative: splitTerms(structured.negative_prompt_terms || promptSections.negative).join(", "),
    bust_breasts: String(bodyProfile.bust_breasts || ""),
    buttocks_glutes: String(bodyProfile.buttocks_glutes || ""),
    arms_hands_fingers: String(bodyProfile.arms_hands_fingers || ""),
    legs_feet: String(bodyProfile.legs_feet || ""),
    structured_json: formattedJson(structured),
  };
}

function buildExtractionUpdatePayload(editorState) {
  const structured = JSON.parse(editorState.structured_json || "{}");
  const promptSections = objectValue(structured.prompt_sections);
  const bodyProfile = objectValue(structured.body_profile);
  const permanentIdentity = objectValue(structured.permanent_identity);
  structured.prompt_sections = {
    ...promptSections,
    identity: editorState.identity,
    face: editorState.face,
    hair: editorState.hair,
    body_shape: editorState.body_shape,
    pose: editorState.pose,
    clothing: editorState.clothing,
    accessories: editorState.accessories,
    preservation: editorState.preservation,
    negative: editorState.negative,
  };
  structured.body_profile = {
    ...bodyProfile,
    body_prompt: editorState.body_shape || bodyProfile.body_prompt || "",
    bust_breasts: editorState.bust_breasts,
    buttocks_glutes: editorState.buttocks_glutes,
    arms_hands_fingers: editorState.arms_hands_fingers,
    legs_feet: editorState.legs_feet,
  };
  structured.permanent_identity = {
    ...permanentIdentity,
    identity_prompt: editorState.identity || permanentIdentity.identity_prompt || "",
  };
  structured.identity_prompt = editorState.identity || structured.identity_prompt || "";
  structured.negative_prompt_terms = splitTerms(editorState.negative);
  return {
    face_description: editorState.face_description,
    body_description: editorState.body_description,
    structured,
  };
}

const AVATAR_GENERATION_TABS = [
  { id: "profile", label: "Create Profile" },
  { id: "saved_profiles", label: "Saved Profiles" },
];

const AVATAR_PROFILE_DETAIL_TABS = [
  { id: "profile", label: "Profile" },
  { id: "body_depth", label: "Body Depth" },
  { id: "face", label: "Face" },
  { id: "poses", label: "Poses" },
  { id: "generation", label: "Generation" },
];

export function AvatarGenerationCard({
  payload = null,
  busy = false,
  result = null,
  apiBase = "",
  initialTab = "profile",
  initialDetailTab = "profile",
  routeProfileId = "",
  onSaveProfile,
  onSelectProfile,
  onDeleteProfile,
  onExtractProfile,
  onUpdateProfileExtraction,
  onUploadProfileReference,
  onDeleteProfileReference,
  onSetPrimaryFace,
  onExtractFaceProfile,
  onGenerateBodyDepthProfile,
  onBackToProfiles,
  onRefresh,
  visionBusy = false,
}) {
  const profiles = asArray(payload?.profiles);
  const selectedProfileId = String(payload?.selected_profile_id || "").trim();
  const routeProfile = useMemo(
    () => profiles.find((profile) => String(profile?.profile_id || "") === String(routeProfileId || "")),
    [profiles, routeProfileId]
  );
  const [activeTab, setActiveTab] = useState(initialTab === "saved_profiles" ? "saved_profiles" : "profile");
  const [activeDetailTab, setActiveDetailTab] = useState(
    AVATAR_PROFILE_DETAIL_TABS.some((tab) => tab.id === initialDetailTab) ? initialDetailTab : "profile"
  );
  const [characterName, setCharacterName] = useState("");
  const [faceFile, setFaceFile] = useState(null);
  const [bodyFile, setBodyFile] = useState(null);
  const [bodyDepthFiles, setBodyDepthFiles] = useState([]);
  const [faceAnalysisFiles, setFaceAnalysisFiles] = useState([]);
  const [poseFiles, setPoseFiles] = useState([]);
  const [poseText, setPoseText] = useState("");
  const [description, setDescription] = useState("");
  const [localStatus, setLocalStatus] = useState("");
  const [activeProfileAction, setActiveProfileAction] = useState("");
  const [activeReferenceAction, setActiveReferenceAction] = useState("");
  const [editorState, setEditorState] = useState(() => extractionEditorState(routeProfile));
  const latestProfile = result?.profile || profiles[0] || null;
  const canSave = Boolean(characterName.trim()) && Boolean(faceFile) && Boolean(bodyFile) && !busy;
  const detailMode = Boolean(routeProfileId);

  useEffect(() => {
    if (routeProfile) {
      setEditorState(extractionEditorState(routeProfile));
    }
  }, [routeProfile]);

  function updateEditorField(name, value) {
    setEditorState((current) => ({ ...current, [name]: value }));
  }

  async function saveProfile(event) {
    event.preventDefault();
    if (!canSave) {
      return;
    }
    setLocalStatus("");
    const [faceData, bodyData] = await Promise.all([fileToDataUrl(faceFile), fileToDataUrl(bodyFile)]);
    const saveResult = await onSaveProfile?.({
      name: characterName.trim(),
      description: description.trim(),
      face_image_filename: faceFile?.name || "face.png",
      face_image_data_base64: faceData,
      body_image_filename: bodyFile?.name || "body.png",
      body_image_data_base64: bodyData,
    });
    if (saveResult?.profile) {
      setLocalStatus("saved");
      setActiveTab("saved_profiles");
    }
  }

  async function runProfileAction(action, profileId, callback) {
    const normalized = String(profileId || "").trim();
    if (!normalized || busy) {
      return;
    }
    setActiveProfileAction(`${action}:${normalized}`);
    setLocalStatus("");
    const actionResult = await callback?.(normalized);
    if (actionResult) {
      setLocalStatus(action);
    }
    setActiveProfileAction("");
  }

  async function saveExtractionEdits(event) {
    event.preventDefault();
    if (!routeProfile?.profile_id || busy) {
      return;
    }
    setLocalStatus("");
    try {
      const payload = buildExtractionUpdatePayload(editorState);
      const updateResult = await onUpdateProfileExtraction?.(routeProfile.profile_id, payload);
      if (updateResult) {
        setLocalStatus("saved");
      }
    } catch (err) {
      setLocalStatus("invalid_json");
    }
  }

  async function uploadReferenceFiles(role, files) {
    const selectedFiles = Array.from(files || []);
    if (!routeProfile?.profile_id || !selectedFiles.length || busy) {
      return;
    }
    setActiveReferenceAction(`upload:${role}`);
    setLocalStatus("");
    try {
      for (const file of selectedFiles) {
        const dataBase64 = await fileToDataUrl(file);
        await onUploadProfileReference?.(routeProfile.profile_id, {
          role,
          name: file.name ? file.name.replace(/\.[^.]+$/, "") : role,
          filename: file.name || `${role}.png`,
          data_base64: dataBase64,
        });
      }
      setLocalStatus("uploaded");
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function deleteReference(role, filename) {
    if (!routeProfile?.profile_id || !filename || busy) {
      return;
    }
    setActiveReferenceAction(`delete:${role}:${filename}`);
    setLocalStatus("");
    try {
      const result = await onDeleteProfileReference?.(routeProfile.profile_id, role, filename);
      if (result) {
        setLocalStatus("deleted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function generateBodyDepthProfile() {
    if (!routeProfile?.profile_id || busy) {
      return;
    }
    const sources = rawBodyReferences(routeProfile).map((reference) => String(reference.filename || "").trim()).filter(Boolean);
    setActiveReferenceAction("generate:body_depth");
    setLocalStatus("");
    try {
      const result = await onGenerateBodyDepthProfile?.(routeProfile.profile_id, {
        source_filenames: sources.length ? sources : null,
        width: 768,
        height: 1152,
        depth_resolution: 1024,
        replace_source_images: true,
      });
      if (result) {
        setLocalStatus("submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function setPrimaryFace(filename) {
    if (!routeProfile?.profile_id || !filename || busy) {
      return;
    }
    setActiveReferenceAction(`primary:face:${filename}`);
    setLocalStatus("");
    try {
      const result = await onSetPrimaryFace?.(routeProfile.profile_id, filename);
      if (result) {
        setLocalStatus("primary_face_selected");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function extractFaceProfile() {
    if (!routeProfile?.profile_id || busy || visionBusy) {
      return;
    }
    const sources = profileReferences(routeProfile, "face").map((reference) => String(reference.filename || "").trim()).filter(Boolean);
    setActiveReferenceAction("extract:face");
    setLocalStatus("");
    try {
      const result = await onExtractFaceProfile?.(routeProfile.profile_id, {
        source_filenames: sources.length ? sources : null,
      });
      if (result) {
        setLocalStatus("face_profile_extracted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  function renderReferenceCards(role, references = profileReferences(routeProfile, role)) {
    if (!references.length) {
      return <p className="muted tiny">No saved references.</p>;
    }
    return (
      <div className="avatar-reference-card-grid">
        {references.map((reference) => {
          const filename = String(reference.filename || "").trim();
          return (
            <article className="avatar-reference-card" key={`${role}:${filename}`}>
              {reference.url ? (
                <a href={profileImageUrl(apiBase, reference.url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, reference.url)} alt={reference.name || filename} />
                </a>
              ) : null}
              <div>
                <strong>{reference.name || filename}</strong>
                <span>{reference.created_at || filename}</span>
                {role === "face" && reference.primary ? <StatusBadge value="primary" /> : null}
              </div>
              {role === "face" && !reference.primary ? (
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => setPrimaryFace(filename)}
                >
                  {activeReferenceAction === `primary:face:${filename}` ? "Selecting..." : "Set Primary"}
                </button>
              ) : null}
              <button
                className="btn btn-danger"
                type="button"
                disabled={busy}
                onClick={() => deleteReference(role, filename)}
              >
                {activeReferenceAction === `delete:${role}:${filename}` ? "Deleting..." : "Delete"}
              </button>
            </article>
          );
        })}
      </div>
    );
  }

  if (detailMode) {
    if (!routeProfile) {
      return (
        <article className="card operational-card-full-span">
          <CardHeader title="Avatar Generation" subtitle="Profile not found." />
          <div className="row">
            <button className="btn" type="button" onClick={onBackToProfiles}>
              Back
            </button>
            <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
              Refresh
            </button>
          </div>
        </article>
      );
    }

    return (
      <article className="card operational-card-full-span avatar-profile-detail">
        <CardHeader title={profileName(routeProfile)} subtitle="Avatar Generation" />
        <div className="row avatar-profile-detail-actions">
          <button className="btn" type="button" onClick={onBackToProfiles}>
            Back
          </button>
          <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
            Refresh
          </button>
          {localStatus ? <StatusBadge value={localStatus} /> : null}
        </div>

        <div className="avatar-generation-tabs" role="tablist" aria-label="Avatar profile tabs">
          {AVATAR_PROFILE_DETAIL_TABS.map((tab) => (
            <button
              className={activeDetailTab === tab.id ? "btn btn-primary" : "btn"}
              key={tab.id}
              onClick={() => setActiveDetailTab(tab.id)}
              role="tab"
              type="button"
              aria-selected={activeDetailTab === tab.id}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeDetailTab === "profile" ? (
          <form className="setup-form avatar-extraction-form" onSubmit={saveExtractionEdits}>
            <div className="avatar-profile-images avatar-profile-detail-images">
              {routeProfile.face_url ? (
                <a href={profileImageUrl(apiBase, routeProfile.face_url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, routeProfile.face_url)} alt={`${profileName(routeProfile)} face`} />
                </a>
              ) : null}
              {routeProfile.body_url ? (
                <a href={profileImageUrl(apiBase, routeProfile.body_url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, routeProfile.body_url)} alt={`${profileName(routeProfile)} body`} />
                </a>
              ) : null}
            </div>
            <div className="form-grid two-column-form-grid">
              <label>
                Face Description
                <textarea rows={9} value={editorState.face_description} onChange={(event) => updateEditorField("face_description", event.target.value)} />
              </label>
              <label>
                Body Description
                <textarea rows={9} value={editorState.body_description} onChange={(event) => updateEditorField("body_description", event.target.value)} />
              </label>
              <label>
                Identity
                <textarea rows={5} value={editorState.identity} onChange={(event) => updateEditorField("identity", event.target.value)} />
              </label>
              <label>
                Face
                <textarea rows={5} value={editorState.face} onChange={(event) => updateEditorField("face", event.target.value)} />
              </label>
              <label>
                Hair
                <textarea rows={4} value={editorState.hair} onChange={(event) => updateEditorField("hair", event.target.value)} />
              </label>
              <label>
                Body Shape
                <textarea rows={6} value={editorState.body_shape} onChange={(event) => updateEditorField("body_shape", event.target.value)} />
              </label>
              <label>
                Bust / Breasts
                <textarea rows={4} value={editorState.bust_breasts} onChange={(event) => updateEditorField("bust_breasts", event.target.value)} />
              </label>
              <label>
                Buttocks / Glutes
                <textarea rows={4} value={editorState.buttocks_glutes} onChange={(event) => updateEditorField("buttocks_glutes", event.target.value)} />
              </label>
              <label>
                Arms / Hands / Fingers
                <textarea rows={4} value={editorState.arms_hands_fingers} onChange={(event) => updateEditorField("arms_hands_fingers", event.target.value)} />
              </label>
              <label>
                Legs / Feet
                <textarea rows={4} value={editorState.legs_feet} onChange={(event) => updateEditorField("legs_feet", event.target.value)} />
              </label>
              <label>
                Pose
                <textarea rows={4} value={editorState.pose} onChange={(event) => updateEditorField("pose", event.target.value)} />
              </label>
              <label>
                Clothing
                <textarea rows={4} value={editorState.clothing} onChange={(event) => updateEditorField("clothing", event.target.value)} />
              </label>
              <label>
                Accessories
                <textarea rows={4} value={editorState.accessories} onChange={(event) => updateEditorField("accessories", event.target.value)} />
              </label>
              <label>
                Negative Terms
                <textarea rows={4} value={editorState.negative} onChange={(event) => updateEditorField("negative", event.target.value)} />
              </label>
            </div>
            <label>
              Structured JSON
              <textarea rows={16} value={editorState.structured_json} onChange={(event) => updateEditorField("structured_json", event.target.value)} />
            </label>
            <div className="row">
              <button className="btn btn-primary" type="submit" disabled={busy || !hasExtraction(routeProfile)}>
                {busy ? "Saving..." : "Save Profile Data"}
              </button>
            </div>
          </form>
        ) : null}

        {activeDetailTab === "body_depth" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="row">
              <label className="avatar-upload-control">
                <span className="btn btn-primary">{activeReferenceAction === "upload:body_depth" ? "Uploading..." : "Upload Body Images"}</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    setBodyDepthFiles(files);
                    uploadReferenceFiles("body_depth", files);
                  }}
                />
              </label>
              <button className="btn" type="button" disabled={busy} onClick={generateBodyDepthProfile}>
                {activeReferenceAction === "generate:body_depth" ? "Generating..." : "Generate Depth Profile"}
              </button>
            </div>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{bodyDepthFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(bodyDepthFiles)}</code>
              <span>Raw Bodies</span>
              <code>{rawBodyReferences(routeProfile).length}</code>
              <span>No-BG Bodies</span>
              <code>{noBgBodyReferences(routeProfile).length}</code>
              <span>Depth Maps</span>
              <code>{profileReferences(routeProfile, "body_depth_map").length}</code>
              <span>Depth Profile</span>
              <StatusBadge value={bodyDepthProfile(routeProfile).status || "not_started"} />
              <span>Generated</span>
              <code>{bodyDepthProfile(routeProfile).generated_count ?? 0}</code>
            </div>
            <div className="avatar-reference-section">
              <h3>Raw Body Images</h3>
              {renderReferenceCards("body_depth", rawBodyReferences(routeProfile))}
            </div>
            <div className="avatar-reference-section">
              <h3>No-BG Body Images</h3>
              {renderReferenceCards("body_depth", noBgBodyReferences(routeProfile))}
            </div>
            <div className="avatar-reference-section">
              <h3>Depth Maps</h3>
              {renderReferenceCards("body_depth_map")}
            </div>
          </section>
        ) : null}

        {activeDetailTab === "face" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="row">
              <label className="avatar-upload-control">
                <span className="btn btn-primary">{activeReferenceAction === "upload:face" ? "Uploading..." : "Upload Face Images"}</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    setFaceAnalysisFiles(files);
                    uploadReferenceFiles("face", files);
                  }}
                />
              </label>
              <button className="btn" type="button" disabled={busy || visionBusy} onClick={extractFaceProfile}>
                {activeReferenceAction === "extract:face" ? "Extracting..." : "Extract Face Profile"}
              </button>
            </div>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{faceAnalysisFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(faceAnalysisFiles)}</code>
              <span>Saved</span>
              <code>{profileReferences(routeProfile, "face").length}</code>
              <span>Primary</span>
              <code>{routeProfile.primary_face_reference_filename || routeProfile.face_image || "base face"}</code>
              <span>PuLID Face</span>
              <code>{routeProfile.pulid_face_reference_image || routeProfile.face_input_image || "none"}</code>
              <span>Face Profile</span>
              <StatusBadge value={faceProfile(routeProfile).status || "not_started"} />
              <span>References</span>
              <code>{faceProfile(routeProfile).reference_count ?? 0}</code>
            </div>
            {faceProfile(routeProfile).structured ? (
              <div className="form-grid two-column-form-grid">
                <label>
                  Identity Prompt
                  <textarea rows={5} readOnly value={String(faceProfile(routeProfile).structured.identity_prompt || "")} />
                </label>
                <label>
                  Face Prompt
                  <textarea rows={5} readOnly value={String(faceProfile(routeProfile).structured.face_prompt || "")} />
                </label>
                <label>
                  Hair Prompt
                  <textarea rows={4} readOnly value={String(faceProfile(routeProfile).structured.hair_prompt || "")} />
                </label>
                <label>
                  Negative Identity
                  <textarea rows={4} readOnly value={String(faceProfile(routeProfile).structured.negative_identity_prompt || "")} />
                </label>
              </div>
            ) : null}
            {renderReferenceCards("face")}
          </section>
        ) : null}

        {activeDetailTab === "poses" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <label className="avatar-upload-control">
              <span className="btn btn-primary">{activeReferenceAction === "upload:pose" ? "Uploading..." : "Upload Pose Images"}</span>
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  setPoseFiles(files);
                  uploadReferenceFiles("pose", files);
                }}
              />
            </label>
            <label>
              Pose Notes
              <textarea rows={8} value={poseText} onChange={(event) => setPoseText(event.target.value)} />
            </label>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{poseFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(poseFiles)}</code>
              <span>Saved</span>
              <code>{profileReferences(routeProfile, "pose").length}</code>
            </div>
            {renderReferenceCards("pose")}
          </section>
        ) : null}

        {activeDetailTab === "generation" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="state-grid compact-grid">
              <span>Profile</span>
              <code>{routeProfile.profile_id}</code>
              <span>Selected</span>
              <StatusBadge value={routeProfile.selected || routeProfile.profile_id === selectedProfileId ? "selected" : "ready"} />
              <span>Extraction</span>
              <StatusBadge value={hasExtraction(routeProfile) ? "ready" : "missing"} />
            </div>
          </section>
        ) : null}
      </article>
    );
  }

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Avatar Generation" subtitle="Create avatar profiles and manage saved profile assets." />

      <div className="avatar-generation-tabs" role="tablist" aria-label="Avatar generation tabs">
        {AVATAR_GENERATION_TABS.map((tab) => (
          <button
            className={activeTab === tab.id ? "btn btn-primary" : "btn"}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            type="button"
            aria-selected={activeTab === tab.id}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "profile" ? (
        <form className="setup-form avatar-profile-form" onSubmit={saveProfile}>
          <div className="form-grid two-column-form-grid">
            <label>
              Character Name
              <input
                type="text"
                value={characterName}
                onChange={(event) => setCharacterName(event.target.value)}
                placeholder="Hexe"
              />
            </label>
            <label>
              Face Image
              <input type="file" accept="image/*" onChange={(event) => setFaceFile(event.target.files?.[0] || null)} />
            </label>
            <label>
              Body Image
              <input type="file" accept="image/*" onChange={(event) => setBodyFile(event.target.files?.[0] || null)} />
            </label>
            <div className="state-grid compact-grid avatar-profile-file-state">
              <span>Face</span>
              <code>{faceFile?.name || "none"}</code>
              <span>Body</span>
              <code>{bodyFile?.name || "none"}</code>
            </div>
          </div>

          <label>
            Character Description
            <textarea rows={10} value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>

          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={!canSave}>
              {busy ? "Saving..." : "Save Profile"}
            </button>
            <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
              Refresh
            </button>
            {localStatus ? <StatusBadge value={localStatus} /> : null}
          </div>
        </form>
      ) : null}

      {activeTab === "saved_profiles" ? (
        <section className="avatar-profile-library">
          <div className="manual-generation-status-grid">
            <div className="status-tile">
              <span>Profiles</span>
              <strong>{profiles.length}</strong>
            </div>
            <div className="status-tile">
              <span>Latest</span>
              <strong>{profileName(latestProfile)}</strong>
            </div>
          </div>

          {profiles.length ? (
            <div className="avatar-profile-list">
              {profiles.map((profile) => (
                <article className="avatar-profile-card" key={profile.profile_id}>
                  <div className="avatar-profile-card-header">
                    <div>
                      <strong>{profileName(profile)}</strong>
                      <span>{profile.updated_at || profile.created_at || "not_saved"}</span>
                    </div>
                    {profile.selected || profile.profile_id === selectedProfileId ? <StatusBadge value="selected" /> : null}
                  </div>
                  <div className="avatar-profile-images">
                    {profile.face_url ? (
                      <a href={profileImageUrl(apiBase, profile.face_url)} target="_blank" rel="noreferrer">
                        <img src={profileImageUrl(apiBase, profile.face_url)} alt={`${profileName(profile)} face`} />
                      </a>
                    ) : null}
                    {profile.body_url ? (
                      <a href={profileImageUrl(apiBase, profile.body_url)} target="_blank" rel="noreferrer">
                        <img src={profileImageUrl(apiBase, profile.body_url)} alt={`${profileName(profile)} body`} />
                      </a>
                    ) : null}
                  </div>
                  {profile.description ? <p className="muted tiny">{profile.description}</p> : null}
                  {profile.extraction?.structured ? (
                    <details className="avatar-profile-json">
                      <summary>Extracted JSON</summary>
                      <pre>{JSON.stringify(profile.extraction.structured, null, 2)}</pre>
                    </details>
                  ) : null}
                  <div className="row avatar-profile-actions">
                    <button
                      className="btn"
                      type="button"
                      disabled={busy || !hasExtraction(profile)}
                      onClick={() => runProfileAction("selected", profile.profile_id, onSelectProfile)}
                    >
                      {!hasExtraction(profile)
                        ? "Extract First"
                        : activeProfileAction === `selected:${profile.profile_id}`
                          ? "Selecting..."
                          : profile.selected || profile.profile_id === selectedProfileId
                            ? "Open"
                            : "Select"}
                    </button>
                    <button
                      className="btn"
                      type="button"
                      disabled={busy}
                      onClick={() => runProfileAction("extracted", profile.profile_id, onExtractProfile)}
                    >
                      {activeProfileAction === `extracted:${profile.profile_id}` ? "Extracting..." : "Extract Data"}
                    </button>
                    <button
                      className="btn btn-danger"
                      type="button"
                      disabled={busy}
                      onClick={() => runProfileAction("deleted", profile.profile_id, onDeleteProfile)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted tiny">No avatar profiles saved.</p>
          )}
        </section>
      ) : null}
    </article>
  );
}
