# Synthia AI Node — Registration Flow

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

After bootstrap discovery, an AI Node registers with Core through HTTP API.

Registration establishes:

- node identity request
- operator approval workflow
- trust activation handoff

Registration is API-only. MQTT is not used for registration transactions.

## Registration Sequence

```text
AI Node
  -> receives valid bootstrap payload
  -> calls register endpoint over HTTP API
Core
  -> creates pending node entry
Operator
  -> approves or rejects in Core UI
Core
  -> returns approval result and trust activation payload (if approved)
AI Node
  -> persists trust state and advances lifecycle
```

## Registration Endpoint

The endpoint URL is composed from validated bootstrap fields:

```text
{api_base}{onboarding_endpoints.register}
```

Example:

```text
http://192.168.1.50:9001/api/nodes/register
```

## Registration Request Payload

Example:

```json
{
  "node_name": "main-ai-node",
  "node_type": "ai-node",
  "node_software_version": "0.1.0",
  "protocol_version": 1,
  "hostname": "ai-server"
}
```

Fields:

| Field | Description |
| --- | --- |
| `node_name` | Human-readable node identifier |
| `node_type` | Must be `"ai-node"` |
| `node_software_version` | Node software version |
| `protocol_version` | Registration protocol compatibility |
| `hostname` | Optional host identifier |

## Core Registration Handling

When Core receives registration request it should:

1. Create a pending node record.
2. Store request metadata.
3. Require operator approval.

Pending registration does not imply trust.

## Pending Approval Response

Example:

```json
{
  "status": "pending_approval",
  "approval_url": "http://core.local/ui/nodes/pending"
}
```

## Node Behavior During Pending Approval

When node receives `pending_approval` it must:

- log/surface approval metadata
- remain in pending approval state
- check status via approval/status flow
- avoid repeated registration re-submit

## Operator Approval

Operator approval is a required Core UI security control.

Approved nodes continue to trust activation parsing. Rejected nodes stop onboarding.

## Approval Trust Activation Payload

Canonical approved payload fields:

- `node_id`
- `paired_core_id`
- `node_trust_token`
- `initial_baseline_policy`
- `operational_mqtt_identity`
- `operational_mqtt_token`
- `operational_mqtt_host`
- `operational_mqtt_port`

Example:

```json
{
  "status": "approved",
  "node_id": "node-ai-001",
  "paired_core_id": "core-main",
  "node_trust_token": "REDACTED",
  "initial_baseline_policy": {
    "policy_version": "v1"
  },
  "operational_mqtt_identity": "main-ai-node",
  "operational_mqtt_token": "REDACTED",
  "operational_mqtt_host": "192.168.1.50",
  "operational_mqtt_port": 1883
}
```

## Rejection Response

```json
{
  "status": "rejected"
}
```

Rejected nodes must terminate onboarding.

## Security Principles

- registration is API-only
- approval is operator-controlled
- no trust material is valid before approval
- bootstrap discovery alone never grants trust

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview](../phase1-overview.md)
- [Bootstrap Contract](./bootstrap-contract.md)
- [Trust State](./trust-state.md)
- [Lifecycle States](./lifecycle-states.md)
