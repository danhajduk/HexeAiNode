# Security And Sensitive State

This document maps the repo’s sensitive-state handling to the current implementation.

Verified against:

- [redaction.py](/home/dan/Projects/HexeAiNode/src/ai_node/security/redaction.py)
- [boundaries.py](/home/dan/Projects/HexeAiNode/src/ai_node/security/boundaries.py)
- [provider_credentials_config.py](/home/dan/Projects/HexeAiNode/src/ai_node/config/provider_credentials_config.py)
- [trust_store.py](/home/dan/Projects/HexeAiNode/src/ai_node/trust/trust_store.py)
- [onboarding_logger.py](/home/dan/Projects/HexeAiNode/src/ai_node/diagnostics/onboarding_logger.py)

## Purpose

This repo keeps security-sensitive state local to the node and documents where that state is stored, how it is redacted, and where debug artifacts require extra operator care.

## Sensitive State Categories

### Trust And Runtime Tokens

Sensitive trust-state fields verified in code:

- `node_trust_token`
- `operational_mqtt_token`

Related trusted runtime fields that should still be treated carefully even when not secret by themselves:

- `operational_mqtt_identity`
- `paired_core_id`
- `core_api_endpoint`
- `initial_baseline_policy`

Current storage location:

- `.run/trust_state.json`

Current handling:

- trust state is validated before save and load
- trust-state logs use redaction before structured output
- invalid trust state is reported with non-sensitive failure context

### Provider Credentials

Sensitive provider credential fields verified in code:

- `api_token`
- `service_token`

Current storage location:

- `.run/provider_credentials.json`

Current handling:

- provider credential files are written with `0600` permissions
- read APIs expose masked hints rather than raw token values
- save logs record only the file path, not the raw credentials
- frontend summary payloads expose `api_token_hint` and `service_token_hint`

### Debug And Diagnostic Artifacts

Sensitive or potentially sensitive debug artifacts verified in the current repo:

- `logs/openai_debug.jsonl`
- `logs/onboarding.json`
- `data/response.json`
- `data/promtp_sent.txt`

Why they need caution:

- provider debug logs may contain full request and response bodies
- onboarding diagnostics may include sensitive trust-related structure, even though redaction is applied
- pricing extraction debug artifacts may include raw prompt text or raw model output not intended for normal operator handoff

## Redaction Coverage

Verified redaction keys in [redaction.py](/home/dan/Projects/HexeAiNode/src/ai_node/security/redaction.py):

- `node_trust_token`
- `operational_mqtt_token`
- `token`
- `password`
- `secret`
- `api_key`
- `api_token`
- `service_token`

Current redaction behavior:

- dictionaries are recursively redacted by key
- lists are recursively redacted using the parent key context
- sensitive values become `***REDACTED***`

## Bootstrap Boundary Enforcement

Verified forbidden bootstrap trust fields:

- `node_trust_token`
- `operational_mqtt_token`
- `operational_mqtt_identity`
- `initial_baseline_policy`

Current enforcement:

- bootstrap payloads are rejected when any forbidden field is present
- approval is required before trust activation is accepted

This means bootstrap discovery remains a non-trusted discovery channel rather than a credential delivery path.

## Logging And Diagnostics Behavior

Verified current protections:

- trust-state load logging uses `redact_trust_state(...)`
- onboarding diagnostic logging uses `redact_dict(...)`
- provider credential summaries use masked token hints
- provider credential save logs do not emit raw secrets

Current caveat:

- optional provider debug output and extraction debug artifacts should be treated as sensitive local files even when not every field is a secret token

## Operator Guidance

- do not commit `.run/`, `logs/`, or `data/`
- treat `.run/trust_state.json` and `.run/provider_credentials.json` as restricted local files
- enable provider debug logging only for short-lived debugging sessions
- clear or rotate debug artifacts after investigation when they are no longer needed
- do not paste raw debug artifacts into tickets or shared docs without review

## Compliance Notes

- aligned: trust token redaction in logs
- aligned: bootstrap forbidden-field enforcement
- aligned: provider credential masking in API summaries
- aligned: provider credential file permission hardening
- aligned: diagnostics redaction path for onboarding events
- follow-up: final compliance appendix should reference these exact files as evidence
