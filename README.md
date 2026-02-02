# EVE Control Room

**This repository is NOT the EVE protocol.**

EVE Control Room is the platform UI for browsing, managing, and approving decisions created by the EVE verification engine. It consumes APIs — it never creates truth.

## What This Does
- Project selection and management
- Decision browsing and visualization
- Approval workflows
- Artifact views

## What This Does NOT
- Compute hashes
- Verify decisions (delegates to EVE Core API)
- Store cryptographic state
- Modify decision payloads

All verification is performed by the EVE Core engine, which is a separate, private, audited system.

## Architecture

```
EVE Core (private)          EVE Control Room (this repo)
┌─────────────────┐         ┌──────────────────────┐
│ Trinity API      │◄────────│ API Client            │
│ Hash engine      │         │ Project selector      │
│ Verification     │         │ Decision views        │
│ Approval registry│         │ Approval UI           │
└─────────────────┘         └──────────────────────┘
   Source of truth             Display layer only
```

## Project Model

Every view and every API call requires an explicit `project_id`. There are no defaults, no fallbacks, no implicit selection.

```typescript
type Project = {
  project_id: string      // e.g. "compliedocs-core"
  label: string
  status: "active" | "archived"
  policy: null             // future packaging hook
  license: null            // future packaging hook
  sku: null                // future packaging hook
}
```

## Rules
- No view without selected project
- No API call without project_id
- "legacy" is never valid in UI
- Backend is always authority
- Never interpret, infer, or "fix" data from the API

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AI_GUARDRAILS.md](AI_GUARDRAILS.md).

AI-assisted contributions are welcome in this repository, subject to the guardrails defined above.

## About EVE

EVE (Evidence & Verification Engine) is a deterministic AI governance platform for regulated industries. Our core verification engine is proprietary and audited. The Control Room UI is open for transparency and trust.

Built by [Organiq Sweden AB](https://organiq.se) — Patent Pending (EVE-PAT-2026-001)
