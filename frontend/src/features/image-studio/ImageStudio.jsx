import { useMemo, useState } from "react";

const CREATION_TYPES = [
  {
    id: "character",
    title: "Character",
    description: "Create a reusable identity, portrait, full-body character, pose, or character edit.",
    icon: "◉",
  },
  {
    id: "location",
    title: "Location",
    description: "Create a reusable interior, exterior, or environmental reference without characters.",
    icon: "⌂",
  },
  {
    id: "scene",
    title: "Scene",
    description: "Compose characters, locations, actions, lighting, and camera direction into one image.",
    icon: "▣",
  },
];

function templateCreationType(template) {
  const domain = String(template?.metadata?.domain || "").trim().toLowerCase();
  const intent = String(template?.metadata?.edit_intent || "").trim().toLowerCase();
  const searchable = `${domain} ${intent}`;
  if (/scene|composition|cinematic/.test(searchable)) {
    return "scene";
  }
  if (/location|place|environment|interior|exterior/.test(searchable)) {
    return "location";
  }
  if (/avatar|character|portrait|face|body|clothing/.test(searchable)) {
    return "character";
  }
  return "unclassified";
}

export function ImageStudio({ templates = [], onOpenLegacy, onClose }) {
  const [creationType, setCreationType] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const matchingTemplates = useMemo(
    () => templates.filter((template) => templateCreationType(template) === creationType),
    [creationType, templates]
  );
  const selectedTemplate = matchingTemplates.find((template) => template.template_id === selectedTemplateId) || null;

  function selectCreationType(type) {
    setCreationType(type);
    setSelectedTemplateId("");
  }

  return (
    <section className="image-studio-shell">
      <header className="image-studio-header">
        <div>
          <span className="image-studio-eyebrow">Hexe Image Studio</span>
          <h1>Create an image</h1>
          <p>Start with the kind of reusable asset or composed image you want to make.</p>
        </div>
        <div className="row">
          <button className="btn" type="button" onClick={onOpenLegacy}>Legacy Generator</button>
          <button className="btn" type="button" onClick={onClose}>Close Studio</button>
        </div>
      </header>

      <div className="image-studio-progress" aria-label="Image Studio steps">
        <div className="is-active"><span>1</span><strong>Creation type</strong></div>
        <div className={creationType ? "is-active" : ""}><span>2</span><strong>Template</strong></div>
        <div><span>3</span><strong>Creative setup</strong></div>
        <div><span>4</span><strong>Generate</strong></div>
      </div>

      {!creationType ? (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading">
            <span>Step 1</span>
            <h2>What are you creating?</h2>
            <p>Choose the asset type first. The studio will only show workflows designed for that purpose.</p>
          </div>
          <div className="image-studio-type-grid">
            {CREATION_TYPES.map((type) => (
              <button className="image-studio-type-card" type="button" key={type.id} onClick={() => selectCreationType(type.id)}>
                <span className="image-studio-type-icon">{type.icon}</span>
                <strong>{type.title}</strong>
                <p>{type.description}</p>
                <span className="image-studio-card-action">Choose {type.title} →</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading image-studio-stage-heading-row">
            <div>
              <span>Step 2</span>
              <h2>{`Choose a ${creationType} template`}</h2>
              <p>Templates define the required references, model workflow, and available controls.</p>
            </div>
            <button className="btn" type="button" onClick={() => selectCreationType("")}>← Change type</button>
          </div>
          {matchingTemplates.length ? (
            <div className="image-studio-template-grid">
              {matchingTemplates.map((template) => {
                const selected = template.template_id === selectedTemplateId;
                return (
                  <button
                    className={`image-studio-template-card ${selected ? "is-selected" : ""}`}
                    type="button"
                    key={template.template_id}
                    onClick={() => setSelectedTemplateId(template.template_id)}
                  >
                    <span>{template.metadata?.input_mode || "image generation"}</span>
                    <strong>{template.template_name || template.template_id}</strong>
                    <p>{template.description || "No workflow description is available yet."}</p>
                    <small>{template.metadata?.edit_intent?.replaceAll("_", " ") || template.template_id}</small>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="image-studio-empty-state">
              <strong>{`No ${creationType} templates are installed yet.`}</strong>
              <p>This workspace is ready for the new template family. Existing character workflows remain safely available.</p>
              <button className="btn" type="button" onClick={() => selectCreationType("")}>Choose another type</button>
            </div>
          )}
          {selectedTemplate ? (
            <div className="image-studio-selection-bar">
              <div><span>Selected workflow</span><strong>{selectedTemplate.template_name || selectedTemplate.template_id}</strong></div>
              <button className="btn btn-primary" type="button" disabled>Creative setup — coming next</button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

export { templateCreationType };
