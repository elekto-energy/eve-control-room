# EVE Control Room

Platform UI for EVE — project management, decisions, approvals.

## Scope
- Project selection and management
- Decision browsing and visualization
- Approval workflows
- Artifact views

## Explicit Non-Goals
- Cryptographic logic
- Hash computation
- Decision verification
- Trinity protocol changes

All verification delegates to EVE Core APIs.

## Rules
- No view without selected project
- No API call without project_id
- "legacy" never valid in UI
- Projects are flat — no hierarchy

(c) 2026 Organiq Sweden AB
