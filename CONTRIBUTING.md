# Contributing to EVE Control Room

This repository is a UI shell. It consumes EVE Core APIs.

## Allowed
- UI components, state management, API clients
- Tests, refactoring, UX improvements
- AI-assisted code generation (reviewed before merge)

## Forbidden
- Hash computation
- Verification logic
- Decision payload modification
- Legacy fallbacks
- Inferring or guessing project_id

## Review Checklist
- [ ] No hash logic introduced
- [ ] No fallback to legacy
- [ ] project_id always explicit
- [ ] Packaging hooks untouched (null)
- [ ] UI fails without project selection

(c) 2026 Organiq Sweden AB
