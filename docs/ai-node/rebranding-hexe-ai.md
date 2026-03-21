# Hexe AI Node Rebranding

## Purpose

This document defines the Phase 1 display-branding migration for the AI Node repository as the platform identity moves from Synthia to Hexe.

The goal of this phase is to update user-facing branding without changing stable runtime contracts or protocol identifiers that other systems already depend on.

## Rebranding Scope

This phase updates display-oriented surfaces such as:

- README and local documentation titles
- UI labels and onboarding copy
- human-readable API/status text
- startup banners and console output
- capability descriptions and other descriptive metadata
- prompt templates or response wrappers when they include user-facing branding

The preferred user-facing naming in this phase is:

- `Hexe AI Node`
- `Hexe AI`
- `Hexe Core`

## Not Rebranded In This Phase

The following items stay on legacy identifiers unless a later migration explicitly changes them:

- MQTT topics
- capability IDs
- task family IDs
- field names and response schemas
- node IDs and other persisted internal identifiers
- machine-parsed headers or protocol-level names that could break compatibility

Examples:

- `X-Synthia-Node-Id` remains unchanged if it is part of an existing wire contract
- internal Python package names such as `ai_node` remain unchanged
- persisted identifiers must not be rewritten as part of display-branding work

## Core Dependency

This rebrand depends on Core-owned migration phases outside this repository.

### Core Phase 0

Core Phase 0 provides the platform branding direction and naming abstraction the node should mirror in user-facing surfaces. This repository should align to the current Core display vocabulary but must not invent protocol migrations on its own.

### Core Phase 1

Core Phase 1 is responsible for any shared or protocol-level namespace migration that affects:

- API header names
- MQTT topic names
- cross-repository identifiers
- Core-issued contracts consumed by the node

Until that phase is completed in Core, this repository must preserve compatibility by keeping legacy internal/protocol identifiers in place.

## Implementation Rule

When a string is visible to operators, documentation readers, or UI users, prefer Hexe branding.

When a string is part of a stable contract, storage key, identifier, capability key, topic, or machine integration point, preserve the legacy value unless a later Core-approved migration changes it.

## Compatibility Note

During this phase, mixed naming is expected in the codebase:

- display text may say `Hexe AI Node`
- internal code and protocol identifiers may still reference `Synthia`

That mixed state is intentional and should be treated as a compatibility requirement, not a cleanup bug.
