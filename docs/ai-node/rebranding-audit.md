# Hexe Rebranding Audit

Status: Active
Last updated: 2026-03-20

## Scope

This audit classifies the remaining hardcoded `Synthia` naming in the repository after the Hexe display-branding pass.

## Replace Now

These were user-facing or documentation-facing strings and were updated in this pass:

- app title, header, onboarding copy, and setup status copy
- README and primary node documentation titles
- runtime startup and console-facing log messages
- systemd service descriptions
- capability display labels for resolved task families in the dashboard and diagnostics view

## Keep For Compatibility

These items still use legacy naming intentionally because they are protocol or integration identifiers:

- MQTT topics such as `synthia/bootstrap/core` and `synthia/nodes/{node_id}/status`
- HTTP headers such as `X-Synthia-Node-Id` and `X-Synthia-Admin-Token`
- service IDs and unit names such as `synthia-ai-node-backend.service`
- API root service identifier `synthia-ai-node-control-api`
- local storage keys such as `synthia_theme`
- package names such as `synthia-ai-node-frontend`
- repository and path references such as `SynthiaCore` and `/home/dan/Projects/Synthia`

## Historical Or External References

These items may still mention `Synthia` because they reference legacy external repository names, historical artifacts, or protocol examples:

- links into the Core repository hosted as `SynthiaCore`
- mismatch or golden-doc artifacts under `docs/`
- example payload values where the field remains valid but the sample has not been normalized yet

## Cleanup List

- Review historical docs outside `docs/ai-node/` and normalize display branding where the content is meant to describe the current operator experience.
- Leave protocol examples unchanged when the literal string is contract-sensitive.
- Preserve `SynthiaCore` path/repository references until the Core repository itself is renamed.
- Preserve `synthia-*` unit names, topics, and headers until the coordinated Core migration phase changes those contracts.
