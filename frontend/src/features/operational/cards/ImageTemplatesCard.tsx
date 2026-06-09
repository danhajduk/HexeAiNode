import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function templateList(payload) {
  return asArray(payload?.state?.templates);
}

function catalogList(payload) {
  return asArray(payload?.templates);
}

function promptList(payload) {
  return asArray(payload?.state?.prompt_services);
}

function variableNames(template) {
  const variables = asArray(template?.variables);
  if (!variables.length) {
    return "none";
  }
  return variables
    .map((variable) => String(variable?.name || variable || "").trim())
    .filter(Boolean)
    .join(", ");
}

function templateBindings(templateId, prompts) {
  return prompts
    .filter((prompt) => prompt?.constraints?.image_template?.template_id === templateId)
    .map((prompt) => ({
      promptId: prompt.prompt_id,
      promptVersion: prompt.current_version,
      status: prompt.status,
    }));
}

function catalogById(catalogTemplates) {
  return new Map(catalogTemplates.map((template) => [template?.template_id, template]));
}

export function ImageTemplatesCard({
  imageTemplatePayload = null,
  comfyuiTemplateCatalogPayload = null,
  promptServicesPayload = null,
}) {
  const templates = templateList(imageTemplatePayload);
  const catalogTemplates = catalogList(comfyuiTemplateCatalogPayload);
  const prompts = promptList(promptServicesPayload);
  const catalogMap = catalogById(catalogTemplates);
  const catalogErrors = asArray(comfyuiTemplateCatalogPayload?.errors);

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Image Templates" subtitle="Registered ComfyUI workflow templates, validation state, and prompt bindings." />
      <div className="state-grid">
        <span>Registered</span>
        <code>{templates.length}</code>
        <span>Catalog</span>
        <StatusBadge value={comfyuiTemplateCatalogPayload?.summary?.valid ? "configured" : "failed"} />
        <span>Catalog Templates</span>
        <code>{catalogTemplates.length}</code>
        <span>Output Policy</span>
        <code>operational</code>
      </div>
      {catalogErrors.length ? (
        <p className="warning tiny">
          Template validation: <code>{catalogErrors.join(", ")}</code>
        </p>
      ) : null}
      <div className="compact-table-wrap">
        <table className="compact-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>State</th>
              <th>Runtime</th>
              <th>Variables</th>
              <th>Prompts</th>
            </tr>
          </thead>
          <tbody>
            {templates.length ? (
              templates.map((template) => {
                const currentVersion = asArray(template?.versions).find(
                  (version) => version?.version === template?.current_version
                ) || asArray(template?.versions)[0] || {};
                const catalogTemplate = catalogMap.get(template?.template_id);
                const bindings = templateBindings(template?.template_id, prompts);
                return (
                  <tr key={template?.template_id}>
                    <td>
                      <strong>{template?.template_name || template?.template_id}</strong>
                      <code>{template?.template_id}</code>
                    </td>
                    <td><StatusBadge value={template?.status || "unknown"} /></td>
                    <td><code>{currentVersion?.runtime_id || "unknown"}</code></td>
                    <td><span className="muted tiny">{variableNames(catalogTemplate || currentVersion)}</span></td>
                    <td>
                      {bindings.length ? (
                        bindings.map((binding) => (
                          <span className="inline-code-list-item" key={`${template?.template_id}:${binding.promptId}`}>
                            <code>{binding.promptId}</code>
                            <span className="muted tiny">{binding.promptVersion || "current"} / {binding.status || "unknown"}</span>
                          </span>
                        ))
                      ) : (
                        <span className="muted tiny">none</span>
                      )}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={5}><span className="muted tiny">No registered image templates.</span></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {catalogTemplates.length ? (
        <div className="template-catalog-strip">
          {catalogTemplates.map((template) => (
            <span className="template-catalog-chip" key={template?.template_id}>
              <code>{template?.template_id}</code>
              <span>{variableNames(template)}</span>
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}
