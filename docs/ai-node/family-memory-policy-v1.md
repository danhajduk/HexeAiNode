# Family Memory Policy v1

Status: initial implementation foundation

Coordination: `HEXE-AI-0001`

Core contract: `hexe.family-identity-authorization.v1`

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

All models use explicit schema versions. Semantic or cardinality changes require
a new version; optional additions remain deny-by-default until understood.

## Deterministic Evaluation

`evaluate_family_memory_access` rejects missing, future, expired, wrong-Core,
wrong-household, wrong-room, denied, mismatched-action, mismatched-visibility,
out-of-scope subject, missing-consent, uncertain-identity, guest-private, and
multi-participant private requests. An allow result contains only the requested
intersection of subject identifiers and visibility.

Replay enforcement, trusted service-token binding, storage, deletion receipts,
export, and retrieval integration remain separate implementation steps. Callers
must not interpret this pure policy evaluator as verification that a context was
authentically issued by Core.
