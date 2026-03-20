# Documentation Policy

This repository keeps documentation for the Synthia AI Node implementation only.

## What Belongs Here

Node repo owns:
- node overview
- node architecture
- setup and deployment steps for this repo
- configuration used by this repo
- runtime behavior implemented in this repo
- troubleshooting and operations for this repo
- node-specific integration details
- node-local APIs, storage, and processing flows

## What Belongs In Synthia Core

Synthia Core owns:
- generic node lifecycle
- trust onboarding model
- capability declaration contract
- governance model
- shared MQTT standards
- shared payload contracts
- global platform terminology
- platform-wide architecture

## Local Core Docs Convenience

`docs/Core-Documents/` exists locally as a symlink to the Synthia Core `docs/` directory, but it is not part of this repository's committed contract.

- Canonical references must always use the Synthia Core GitHub links listed in [core-references.md](./core-references.md).
- Local symlink paths are provided only as developer convenience.
- The docs in this repo must stay readable on GitHub even when `docs/Core-Documents/` does not exist.
