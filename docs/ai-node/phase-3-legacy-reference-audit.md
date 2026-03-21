# Hexe AI Node — Phase 3 Legacy Reference Audit

Status: Active
Last updated: 2026-03-20

## Runtime

Keep for compatibility:

- `X-Synthia-Node-Id` headers in Core API clients
- `X-Synthia-Admin-Token` header names in control API and frontend API client
- `synthia-ai-node-control-api` root service identifier
- `synthia-ai-node-backend.service` and `synthia-ai-node-frontend.service` unit identifiers in runtime helpers
- `Synthia Core` bootstrap example values until Core-owned sample payload naming is revised

Rename locally when safe:

- internal helper/variable names that are not part of the external wire contract
- local storage keys such as `synthia_theme`
- package metadata such as `synthia-ai-node-frontend`

## Display

Already updated in prior phases:

- app title
- setup/onboarding copy
- runtime startup banners
- capability display labels

No additional active display `Synthia` strings were found in the main UI/runtime surfaces during this audit.

## Docs

Keep as external or historical references:

- `SynthiaCore` repository links in core-reference docs
- local `/home/dan/Projects/Synthia` path references
- migration/audit docs that intentionally describe the old namespace or old branding

Rename now:

- active docs that still describe the current platform using legacy branding
- script/example docs that are not contract-sensitive

## Tests

Keep for compatibility:

- tests that assert `X-Synthia-*` header names

Rename now:

- tests asserting local-only names, comments, and non-wire labels

## Archive

Mark clearly historical:

- golden mismatch artifacts
- archived repo-audit templates
- previous rebrand and namespace audit notes once Phase 3 is complete

## Next Safe Cleanup Targets

- update script examples and developer-facing paths where they are descriptive rather than canonical
- revise Core-owned example payload naming when the corresponding Core docs are updated
