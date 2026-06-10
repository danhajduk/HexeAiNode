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

const AVATAR_GENERATION_TABS = [
  { id: "profile", label: "Create Profile" },
  { id: "saved_profiles", label: "Saved Profiles" },
];

export function AvatarGenerationCard({
  payload = null,
  busy = false,
  result = null,
  apiBase = "",
  initialTab = "profile",
  onSaveProfile,
  onSelectProfile,
  onDeleteProfile,
  onExtractProfile,
  onRefresh,
}) {
  const profiles = asArray(payload?.profiles);
  const selectedProfileId = String(payload?.selected_profile_id || "").trim();
  const [activeTab, setActiveTab] = useState(initialTab === "saved_profiles" ? "saved_profiles" : "profile");
  const [characterName, setCharacterName] = useState("");
  const [faceFile, setFaceFile] = useState(null);
  const [bodyFile, setBodyFile] = useState(null);
  const [description, setDescription] = useState("");
  const [localStatus, setLocalStatus] = useState("");
  const [activeProfileAction, setActiveProfileAction] = useState("");
  const latestProfile = result?.profile || profiles[0] || null;
  const canSave = Boolean(characterName.trim()) && Boolean(faceFile) && Boolean(bodyFile) && !busy;

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
                      disabled={busy || profile.selected || profile.profile_id === selectedProfileId}
                      onClick={() => runProfileAction("selected", profile.profile_id, onSelectProfile)}
                    >
                      {profile.selected || profile.profile_id === selectedProfileId ? "Selected" : "Select"}
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
