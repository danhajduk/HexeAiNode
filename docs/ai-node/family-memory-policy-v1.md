# Family Memory Policy v1

Status: initial implementation foundation

Coordination: `HEXE-AI-0001`

Core contract: `hexe.family-identity-authorization.v1`

Canonical contract artifact:
`HexeCoordination/contracts/accepted/family-identity-authorization-v1.md`.

This policy defines the AI Node's first fail-closed family-memory boundary. It
does not enable durable memory storage or claim that Core's family identity
runtime is available. Until Core supplies a valid short-lived authorization
context, private and family-aware memory operations are denied.

## Responsibility Boundary

Core owns household, person, user, role, guardian, consent, room, device, and
authorization decisions. The AI Node validates the received context and may
narrow it, but never broadens it. Room or endpoint context can constrain an
operation; neither proves identity nor grants memory access.

## Memory Visibility Matrix

| Visibility | Required subject and audience | Minimum identity | Guest/unknown behavior |
| --- | --- | --- | --- |
| `private` | Exactly one subject; no separate audience | One authenticated, verified, or confirmed participant matching the subject | Denied |
| `explicit` | One or more subjects and an explicit audience | Every affected participant must be authorized | Denied on unknown or conflicted presence |
| `household` | Subjects authorized by Core household policy | Core allow decision and applicable consent | Guest access only when Core explicitly grants the non-private read |
| `room` | Subjects authorized by Core plus the exact current room | Core allow decision; room match is constraining only | No identity or private-access inference from room presence |
| `guardian_managed` | Dependent subject under an active scoped guardian decision | Core allow decision, guardian scope, and applicable consent | Denied |

Private access never falls back to household, room, nearest identity, or a
model-selected person. `probable`, `unknown`, and `conflicted` identity cannot
authorize private or personal-sensitive memory.

## Room Privacy Matrix

| Situation | Retrieval | Durable write/learning |
| --- | --- | --- |
| Private audience, one authorized participant | Authorized private scope only | Only when Core explicitly allows the action and supplies consent evidence |
| Shared/group audience | Intersection safe for every participant | Denied unless every affected subject is authorized |
| Unknown or conflicted participant present | Public/general context only | Denied |
| Probable participant | Household/general low-risk context only when explicitly allowed | Denied by default |
| Guest requester | Explicitly granted non-private reads only | Denied |
| Room mismatch or unclassified room | Denied for room-bound access | Denied |

## Versioned Models

`ai_node.family_memory.models` defines strict, extra-field-forbidden v1 models:

- `FamilyAuthorizationContext` mirrors the accepted Core authorization envelope
  and enforces the 120-second maximum lifetime.
- `FamilyInteractionContext` records bounded interaction provenance without raw
  biometric evidence or transcript content.
- `FamilyMemoryRecord` requires subjects, visibility, consent evidence, source
  provenance, lifecycle state, and timestamps.
- `FamilyMemoryAuditEvent` records opaque identifiers, action, result, and safe
  reason without memory content or raw interaction data.
- `FamilyMemoryLifecycleRequest`, `FamilyMemoryDeletionReceipt`, and
  `FamilyMemoryExportManifest` bind lifecycle operations and evidence to the
  Core authorization, household, subjects, and declared data categories.

All models use explicit schema versions. Semantic or cardinality changes require
a new version; optional additions remain deny-by-default until understood.

## Deterministic Evaluation

`evaluate_family_memory_access` rejects missing, future, expired, wrong-Core,
wrong-household, wrong-room, denied, mismatched-action, mismatched-visibility,
out-of-scope subject, missing-consent, uncertain-identity, guest-private, and
multi-participant private requests. An allow result contains only the requested
intersection of subject identifiers and visibility.

Replay enforcement, trusted service-token binding, deletion execution, export
payload generation, and live request integration remain separate implementation
steps. Callers must not interpret this pure policy evaluator as verification that
a context was authentically issued by Core.

## Node Storage Foundation

`EncryptedFamilyMemoryStore` provides an inactive local persistence primitive for
future family-memory APIs. It requires an externally supplied 256-bit master key,
derives a distinct AES-256-GCM key for each Core, household, and person partition,
hashes scope identifiers in filesystem paths, encrypts the complete record set
and metadata, uses process-safe atomic writes, and sets data files to mode `0600`.
It never generates or persists the master key.

`AuthorizedFamilyMemoryRetriever` evaluates the short-lived Core authorization
context before opening a partition. It then filters by authorized subjects,
visibility, lifecycle status, expiry, and explicit audience before returning a
bounded deterministic result set. Missing or uncertain authorization therefore
cannot probe whether a person's partition or memory exists.

These classes are deliberately not connected to `task.chat`, HTTP routes, or
startup configuration. Production activation still requires Core-issued trusted
authorization contexts, service-token binding, replay enforcement, managed key
provisioning, lifecycle APIs, and audit integration.

## Consent and Child Safety

Consent is purpose-specific and deny-by-default. Every memory record carries at
least one opaque consent identifier. Missing, expired, denied, or revoked consent
denies new reads and writes; revocation also triggers the bounded lifecycle flow
for previously persisted data. Operational personalization consent never implies
model-training consent.

A dependent's memory is `guardian_managed` only when Core supplies an active
guardian decision scoped to the requested purpose, action, and subject. A family
relationship label, platform admin role, room assignment, or device ownership is
not guardian authority. Explicit denial and child-safety policy override grants.
Sensitive actions remain denied unless Core explicitly authorizes them.

## Retention and Expiry

Every durable record has `created_at`, `updated_at`, optional `expires_at`, and a
lifecycle status. Retrieval must exclude expired and deleted records before
ranking or prompt construction. Expiry produces an auditable lifecycle change;
it must not resurrect data from an index, cache, backup, or restored snapshot.
AI Node storage implementations must publish category-specific retention periods
before durable family memory is enabled.

Authorization envelopes are operational inputs, not memory records. They may be
retained only long enough for replay enforcement and a minimized audit reference.
Raw transcripts, biometrics, presence history, and memory content are excluded
from authorization and audit records.

## Deletion

Core sends a versioned, authorized deletion request scoped to `core_id`,
`household_id`, subject identifiers, and declared categories. The node blocks new
access for a deleted subject, removes active records and retrieval-index entries,
and preserves tombstones only where synchronization requires them. Shared records
are redacted or detached according to policy rather than deleting another
subject's private data.

The node returns a bound receipt listing deleted and retained categories. Retained
categories require a policy/legal reason and make the operation `incomplete`; a
receipt cannot mark completion while retaining requested categories. Backup
purging or expiry remains visible until complete.

## Export

Export requires an explicit `memory.export` authorization and applicable consent.
It is limited to the intersection of authorized subject identifiers and
categories, excludes another person's private data, and records an audit event.
The manifest contains opaque scope and counts, not memory content. Export payload
encryption, transport, and signed delivery receipts remain part of the future
storage/API implementation.

## Threat Controls

- Memory text is untrusted data and cannot become system instructions.
- Model output, voice inference, room presence, and caller-provided identifiers
  cannot upgrade identity or authorization.
- Authorization filtering precedes room relevance, semantic ranking, and prompt
  construction.
- Denials reveal no person, consent, relationship, or memory existence.
- Automatic durable learning and biometric authorization remain disabled.
