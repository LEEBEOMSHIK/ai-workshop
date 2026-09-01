---
schema_version: 1
rules:
  - signal: requirements-or-behavior
    required_roles: [requirements-implementation-designer]
  - signal: cross-module-or-public-contract
    required_roles: [system-architect]
  - signal: react-ui
    required_roles: [frontend-engineer]
  - signal: python-api-or-worker
    required_roles: [python-backend-engineer]
  - signal: ai-model-or-runtime
    required_roles: [ai-engineer]
  - signal: database-or-migration
    required_roles: [database-administrator]
  - signal: docker-compose-or-deployment
    required_roles: [infrastructure-docker-engineer]
  - signal: authentication-permission-or-exposure
    required_roles: [security-permission-verifier]
  - signal: privacy-or-external-transfer
    required_roles: [data-privacy-verifier]
  - signal: rag-behavior
    required_roles: [rag-lead]
  - signal: feature-implementation
    required_roles: [test-designer, integration-e2e-verifier]
  - signal: significant-change-or-merge
    required_roles: [independent-code-reviewer]
  - signal: design-adr-or-document-structure
    required_roles: [design-adr-documentation-manager]
---

# Activation rules

The selector returns the minimum mandatory role baseline for the activation signals supplied by the project orchestrator. It does not form a complete contextual roster.

The orchestrator adds only the domain specialists that the actual scope needs, then records the selected roles and the reasons roles were excluded. It must notify the user of participation and exclusion reasons before assigning work.
