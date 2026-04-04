# Frontend Modularity Audit

This document captures the verified frontend modularity findings for the remaining standards-alignment work on the node UI.

## Scope

- Verified against [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx)
- Verified against the current feature folders under [frontend/src/features](/home/dan/Projects/HexeAiNode/frontend/src/features)
- Focused on the Hexe node frontend standard requirement that new and evolving nodes stay modular by responsibility

## Current Verified State

- The frontend already has clear feature folders for setup, operational, diagnostics, and node-UI behavior.
- The operational dashboard is already decomposed into feature-level cards and shell components.
- The setup flow is partly decomposed into `SetupModeView`, `SetupShell`, `SetupStepper`, and setup stage panels.
- [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx) remains the largest coordination file and is still responsible for both app-shell orchestration and several clusters of pure display or transformation logic.

## Extraction Targets Verified In App.jsx

- Shared formatting helpers:
  - local timestamp formatting
  - tier label formatting
  - budget period formatting
  - exact USD formatting
  - token hint masking
- Operational provider-budget helpers:
  - provider budget summarization
  - budget pill display formatting
  - tone derivation for header status pills
- Operational client-usage shaping:
  - prompt service metadata joining
  - client usage normalization for the client-cost dashboard
- Operational OpenAI model presentation logic:
  - model family formatting
  - pricing row derivation
  - capability badge derivation
  - grouped model sorting by family and freshness

## Extraction Work Completed In This Pass

- Shared formatting utilities moved to [formatters.js](/home/dan/Projects/HexeAiNode/frontend/src/shared/formatters.js)
- Provider-budget derivation moved to [providerBudgetSummary.js](/home/dan/Projects/HexeAiNode/frontend/src/features/operational/providerBudgetSummary.js)
- Client-usage normalization moved to [clientUsageSummary.js](/home/dan/Projects/HexeAiNode/frontend/src/features/operational/clientUsageSummary.js)
- OpenAI model presentation helpers moved to [openaiModelPresentation.js](/home/dan/Projects/HexeAiNode/frontend/src/features/operational/openaiModelPresentation.js)

## Remaining App.jsx Responsibilities That Still Belong There

- top-level route and mode resolution
- backend polling and refresh orchestration
- local React state ownership
- API mutation handlers
- setup-flow action wiring
- modal open/close state
- cross-feature props assembly for setup and operational screens

## Remaining Candidates For A Future Pass

- provider setup form rendering is still embedded inside `App.jsx`
- setup action assembly is still embedded inside `App.jsx`
- pricing review modal rendering is still embedded inside `App.jsx`

These are valid future modularity targets, but they are more coupled to local state and event handlers than the pure helper clusters extracted in this pass.
