export function IdentityScreen({
  nodeId,
  mqttHost,
  nodeName,
  saving,
  onMqttHostChange,
  onNodeNameChange,
  onSubmit,
}) {
  return (
    <section className="card setup-card">
      <h2>Setup Node</h2>
      <p className="muted">
        Node is <code>UNCONFIGURED</code>. Enter the bootstrap MQTT host and a friendly name to begin onboarding.
      </p>
      {nodeId ? (
        <p className="muted tiny">
          This node identity is fixed for onboarding: <code>{nodeId}</code>
        </p>
      ) : null}
      <p className="muted tiny">
        Friendly name is sent to Hexe Core as <code>node_name</code>. Spaces are allowed.
      </p>
      <form onSubmit={onSubmit} className="setup-form">
        <label>
          MQTT Host
          <input
            value={mqttHost}
            onChange={(event) => onMqttHostChange(event.target.value)}
            placeholder="10.0.0.100"
            required
          />
        </label>
        <label>
          Friendly Node Name
          <input
            value={nodeName}
            onChange={(event) => onNodeNameChange(event.target.value)}
            placeholder="Main AI Node"
            required
          />
        </label>
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Starting..." : "Start Onboarding"}
        </button>
      </form>
    </section>
  );
}
