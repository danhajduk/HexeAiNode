# Core Prompt Management Follow-up Ticket

Status: Open
Created: 2026-03-20

## Gap

The Core documentation available to this repository does not provide a canonical prompt-governance contract for AI Nodes.

Missing Core-owned artifacts:

- prompt ownership payload and source-of-truth rules
- prompt approval and publication workflow
- canonical lifecycle payload and transition authority
- Core-to-node prompt governance distribution contract
- signed or versioned prompt-governance refresh semantics

## Why This Matters

The AI Node now implements a local prompt-management baseline so prompt versions, lifecycle state, and execution constraints can be enforced immediately. That local surface should eventually converge on a Core-owned contract to avoid drift between node-local prompt state and future Core-managed governance.

## Requested Core Deliverable

Define the canonical Core prompt-governance contract for AI Nodes, including:

- prompt definition envelope
- ownership and approval metadata
- lifecycle state vocabulary and transition authority
- prompt version distribution payload
- provider/model governance fields
- cache refresh and staleness semantics for node enforcement
