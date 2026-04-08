# Runtime

## Startup Behavior

- without trust state, the node starts from `unconfigured` and enters bootstrap onboarding when configured
- with valid trust state, startup resumes through `trusted -> capability_setup_pending`
- trusted resume may continue to operational when accepted capability and fresh governance are already valid

## Reconnect And Retry Behavior

- bootstrap connection is monitored by a timeout guard
- capability and governance flows use explicit result classification for retryable versus rejected failures
- provider capability refresh runs on the `4_times_a_day` internal schedule when enabled

## OpenAI Provider Runtime Behavior

- model capability classification is deterministic and local (`classification_model = deterministic_rules`)
- canonical capability classifications are stored in `providers/openai/provider_model_classifications.json`
- the filtered representative UI catalog is returned by `/api/providers/openai/models/catalog` as `ui_models`; the full normalized filtered catalog remains available as `models`
- provider pricing refresh uses a section-based pipeline:
  1. fetch official source text (`pricing.md` primary, HTML fallback)
  2. normalize source text and cache normalized output
  3. split source into canonical sections (`text_tokens`, `audio_tokens`, `image_generation`, `video`, `other_models`, `embeddings`, `moderation`, and related sections)
  4. extract family-specific source blocks from those sections
  5. run family-scoped extraction prompts against filtered target model IDs only
  6. validate each family output independently and merge successful families
  7. persist canonical pricing snapshot
- giant single-prompt extraction was replaced by family prompts to reduce schema drift, avoid irrelevant context per request, and improve partial failure isolation
- malformed family outputs are rejected without failing the whole refresh when other families succeed
- failed families preserve last-known-good family entries with `fallback_used` status when possible
- pricing schema uses `null` for non-applicable fields instead of `0.0` placeholders (for example, STT/TTS token fields)
- live OpenAI API pricing extraction is disabled by default and `POST /api/providers/openai/pricing/refresh` returns `status = manual_only` until `SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED=true`
- optional manual pricing overrides are loaded from `providers/openai/provider_model_pricing_overrides.json`
- manual pricing saves are persisted into the overrides store so later refreshes do not overwrite saved operator prices
- section-level diagnostics are cached for admin/debug visibility (target models, section source, prompt used, raw result, validation result)
- the provider setup UI reads family-aware pricing from the saved catalog: token models show input/output token prices, and non-token families use `normalized_price` + `normalized_unit`

## Capability Declaration Gate

- capability declaration is manual (`POST /api/capabilities/declare`) and is not auto-triggered by provider/config refresh endpoints
- declaration is blocked until at least one enabled OpenAI model is usable for declaration
- selected OpenAI models that are missing classification or pricing remain visible locally but are treated as unavailable for routing/declaration payloads
- provider intelligence submission excludes unavailable models from `available_models` so Core routing inputs reflect only usable models

## Registration And Trust Assumptions

- onboarding depends on bootstrap MQTT plus Core HTTP APIs
- trust state and node identity must remain internally consistent
- invalid trust or config files are ignored and logged as non-sensitive failures

## Health And Telemetry

- `GET /api/health` returns a simple backend health response
- `GET /api/node/status` exposes lifecycle, trusted runtime context, capability setup state, capability runtime state, service status, and internal scheduler state
- trusted status telemetry publishes over operational MQTT only
- supervisor runtime heartbeats include rolling API metrics (RPS, p95 latency, error rate) plus node process CPU and memory usage when available
- `GET /api/node/status` includes `api_metrics` with rolling RPS, p95 latency, error rate, and node process CPU/memory usage when available

## Runtime Health

- operational MQTT readiness is tracked as runtime health and telemetry context; it is not the lifecycle criterion for entering `operational`
- when operational MQTT health fails after trust is established, the backend now schedules up to 3 automatic backend restarts with a 10 second delay between attempts
- operational MQTT health uses a dynamic scheduler cadence:
  - `every_10_seconds` while the node is trusted, in capability activation, degraded, or in an active recovery window
  - `every_10_seconds` for 5 minutes after backend startup
  - `every_10_seconds` for 5 minutes after the node returns to fully `operational`
  - `every_5_minutes` while the node is stably operational with no active recovery cycle
- the retry cycle is persisted in `.run/operational_mqtt_recovery.json` so attempt counts survive backend restarts

## Degraded Behavior

- temporary capability submission, governance sync, or telemetry failures can transition the node to `degraded`
- operational MQTT outage also uses `degraded` as the operator-visible lifecycle state while automatic restart recovery is in progress or exhausted
- recovery is explicit through the control API and startup resume logic

## Sensitive Runtime Artifacts

- trust and provider credential handling is documented in [security-and-sensitive-state.md](/home/dan/Projects/HexeAiNode/docs/security-and-sensitive-state.md)
- optional provider debug logs and extraction debug artifacts should be treated as sensitive local runtime output

## Shutdown Behavior

- bootstrap runner and timeout monitor are stopped when the backend exits
- provider background tasks are managed through the control app lifecycle
- recurring node-local background work is owned by an internal scheduler that starts and stops through the control app lifecycle and persists task snapshots in `.run/internal_scheduler_state.json`

## Internal Scheduler

- node-local recurring work is modeled explicitly as internal scheduler tasks instead of anonymous background loops
- the current recurring tasks are:
  - provider capability refresh
  - heartbeat
  - telemetry
  - operational MQTT health check
- default named schedules are:
  - `interval_seconds`
  - `heartbeat_5_seconds`
  - `telemetry_60_seconds`
  - `every_10_seconds`
  - `every_5_minutes`
- scheduler task snapshots persist enabled state, schedule details, last success/failure timestamps, current status, and last error for operator visibility
- `GET /api/capabilities/diagnostics` includes the structured internal scheduler payload for admin inspection

## Runtime Path Ownership

- `.run/` is the canonical local state area for trust, onboarding, identity, capability, governance, prompt, budget, and client-usage persistence
- `data/` is used for local derived provider snapshots, caches, and debug extraction artifacts
- `logs/` is the operator-facing log area for backend, frontend, onboarding, and optional provider debug logs
- current path ownership and standard-alignment decision are documented in [runtime-path-ownership.md](/home/dan/Projects/HexeAiNode/docs/runtime-path-ownership.md)
