import { useMemo, useState } from "react";

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

export function AvatarGenerationCard({
  payload = null,
  busy = false,
  visionBusy = false,
  result = null,
  apiBase = "",
  onSaveProfile,
  onDescribeReference,
  onRefresh,
}) {
  const profiles = asArray(payload?.profiles);
  const [activeTab, setActiveTab] = useState("profile");
  const [characterName, setCharacterName] = useState("");
  const [faceFile, setFaceFile] = useState(null);
  const [bodyFile, setBodyFile] = useState(null);
  const [description, setDescription] = useState("");
  const [localStatus, setLocalStatus] = useState("");
  const latestProfile = result?.profile || profiles[0] || null;
  const canSave = Boolean(characterName.trim()) && Boolean(faceFile) && Boolean(bodyFile) && !busy;
  const canDescribe = Boolean(faceFile) && Boolean(bodyFile) && !visionBusy && !busy;
  const tabs = useMemo(
    () => [
      { id: "profile", label: "Profile", disabled: false },
      { id: "body_depth", label: "Body Depth", disabled: true },
      { id: "pose", label: "Pose", disabled: true },
      { id: "avatar", label: "Avatar", disabled: true },
    ],
    []
  );

  async function describeProfile() {
    if (!canDescribe) {
      return;
    }
    setLocalStatus("");
    const faceData = await fileToDataUrl(faceFile);
    const faceResult = await onDescribeReference?.({
      mode: "face",
      image_filename: faceFile?.name || "face.png",
      image_data_base64: faceData,
      custom_prompt:
        "Describe this character's face for avatar identity preservation. Include face shape, visible age range, skin tone, eyes, eyebrows, nose, lips, hair, distinctive features, and expression. Be specific and concise.",
    });
    const bodyData = await fileToDataUrl(bodyFile);
    const bodyResult = await onDescribeReference?.({
      mode: "body",
      image_filename: bodyFile?.name || "body.png",
      image_data_base64: bodyData,
      custom_prompt:
        "Describe this character's body reference for avatar generation. Include full-body proportions, silhouette, body shape, posture, pose angle, limb placement, clothing, visible style, and details useful for preserving the character. Be specific and concise.",
    });
    const nextDescription = [
      characterName.trim() ? `Character name: ${characterName.trim()}` : "",
      faceResult?.description ? `Face: ${String(faceResult.description).trim()}` : "",
      bodyResult?.description ? `Body: ${String(bodyResult.description).trim()}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
    if (nextDescription) {
      setDescription(nextDescription);
      setLocalStatus("description_ready");
    }
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
    }
  }

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Avatar Generation" subtitle="Profile, body-depth, pose, and final avatar workflow." />

      <div className="avatar-generation-tabs" role="tablist" aria-label="Avatar generation tabs">
        {tabs.map((tab) => (
          <button
            className={activeTab === tab.id ? "btn btn-primary" : "btn"}
            disabled={tab.disabled}
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
        <div className="avatar-profile-layout">
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
              <button className="btn" type="button" onClick={describeProfile} disabled={!canDescribe}>
                {visionBusy ? "Describing..." : "Describe With Vision"}
              </button>
              <button className="btn btn-primary" type="submit" disabled={!canSave}>
                {busy ? "Saving..." : "Save Profile"}
              </button>
              <button className="btn" type="button" onClick={onRefresh} disabled={busy || visionBusy}>
                Refresh
              </button>
              {localStatus ? <StatusBadge value={localStatus} /> : null}
            </div>
          </form>

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
                  <article className="avatar-profile-row" key={profile.profile_id}>
                    <div>
                      <strong>{profileName(profile)}</strong>
                      <span>{profile.updated_at || profile.created_at || "not_saved"}</span>
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
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted tiny">No avatar profiles saved.</p>
            )}
          </section>
        </div>
      ) : null}
    </article>
  );
}
