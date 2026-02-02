# ARCH_PROJECT_RUNTIME.md
# EVE Project Runtime Architecture
**Status:** LOCKED  
**Version:** 1.0.0  
**Locked by:** Joakim Eklund  
**Date:** 2026-02-02  
**Commit:** 27ce271 (eve-v2-verified)

---

## 1. Purpose

This document defines the runtime behavior of `project_id` across EVE's decision and approval systems. It is the authoritative reference for how project isolation works end-to-end.

**This document is immutable.** Changes require a new ARCH document with explicit supersession.

---

## 2. Core Principle

> **Project isolation is a hash boundary, not an access control boundary.**

- `project_id` determines which context_hash is computed
- `project_id` does NOT determine who can access what
- Access control remains global (approver_registry)
- Project scoping is a governance decision, not a technical enforcement

---

## 3. Hash Versioning Model

### 3.1 Version Routing

```python
def normalize_project_id(project_id: Optional[str]) -> Tuple[str, str]:
    if not project_id:
        return "legacy", "v1"
    return project_id, "v2"
```

| Input | Output project_id | Output hash_version |
|-------|-------------------|---------------------|
| `None` | `"legacy"` | `"v1"` |
| `""` | `"legacy"` | `"v1"` |
| `"medical-core"` | `"medical-core"` | `"v2"` |

### 3.2 Hash Computation (v2)

```python
context_data = json.dumps({
    "project_id": project_id,      # ← ADDED in v2
    "system_id": ...,
    "use_case": ...,
    "artifacts": ...,
    "risk_links": ...,
    "signoff": ...
}, sort_keys=True)

context_hash = sha256(context_data).hexdigest()
```

### 3.3 Invariant

> Same payload + different `project_id` = different `context_hash`

This is the isolation guarantee.

---

## 4. System Topology

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL TRINITY (port 8000)                                  │
│  Role: Authoring / Workshop / Deterministic execution       │
│  Creates: EVE Decision IDs, context_hash, vault proofs      │
│  project_id: Determines v1/v2 hash routing                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ (decisions created here)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  EXTERNAL TRINITY CLOUD (api.eveverified.com)               │
│  Role: Notary / Publication / Global witness                │
│  Receives: Approval/rejection sync from Knowledge/Artifact  │
│  project_id: Forwarded as metadata                          │
└─────────────────────────────────────────────────────────────┘
```

**Critical:** Local Trinity and Cloud Trinity are NOT parallel systems. They are sequential phases:
1. Local creates decisions
2. Cloud witnesses and publishes

---

## 5. API Contracts

### 5.1 Trinity API (port 8000)

```
POST /execute_ecl
{
  "ecl_command": "...",
  "project_id": "medical-core"  // Optional, null = legacy
}

Response:
{
  "eve_decision_id": "EVE-2026-000001",
  "project_id": "medical-core",
  "hash_version": "v2",
  "context_hash": "abc123..."
}
```

```
GET /decisions?project_id=medical-core
→ Returns only decisions with matching project_id
```

### 5.2 Knowledge API (port 8002)

```
POST /api/approve
{
  "regulation": "gdpr",
  "article_number": "5",
  "approved_by": "joakim",
  "project_id": "medical-core"  // Optional
}
→ Forwards project_id to external Trinity cloud
```

```
GET /api/articles?project_id=medical-core
→ Local view filtering (not governance)
```

### 5.3 Artifact API (port 8003)

```
POST /api/artifacts/{id}/approve
{
  "approved_by": "joakim",
  "note": "Reviewed and approved",
  "project_id": "compliedocs-core"  // Optional
}
→ Forwards project_id to external Trinity cloud
```

```
GET /api/artifacts?project_id=compliedocs-core
→ Local view filtering (not governance)
```

---

## 6. What project_id IS and IS NOT

### IS ✅

- A hash boundary (different project = different context_hash)
- A filtering criterion for list views
- Metadata forwarded to cloud Trinity
- A way to organize decisions by domain

### IS NOT ❌

- An access control mechanism
- A trust boundary (approvers are global)
- A separate database or storage
- Required (null = legacy behavior)

---

## 7. Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Existing v1 clients (no project_id) | Work unchanged, get `hash_version: v1` |
| New v2 clients (with project_id) | Get `hash_version: v2` with isolation |
| Mixed environment | Both coexist, legacy decisions remain valid |
| Verification of old decisions | Use stored `hash_version` to select algorithm |

---

## 8. Governance Boundaries (LOCKED)

| Component | Can modify project_id? | Can create decisions? |
|-----------|------------------------|----------------------|
| Trinity API (8000) | YES (normalizes) | YES |
| Knowledge API (8002) | NO (forwards only) | NO |
| Artifact API (8003) | NO (forwards only) | NO |
| UI | NO (selects only) | NO |

**Only Trinity API creates decisions and computes hashes.**

---

## 9. Test Coverage

| Test Suite | Count | Status |
|------------|-------|--------|
| Trinity v2 hash tests | 24/24 | ✅ |
| E2E sanity tests | 29/29 | ✅ |
| **Total** | **53/53** | ✅ |

Tests verify:
- v1/v2 routing
- Hash isolation between projects
- Deterministic behavior
- Backward compatibility
- Filter logic

---

## 10. Future Extensions (NOT in scope now)

These are explicitly deferred:

- [ ] Project Registry (read-only metadata)
- [ ] UI project selector
- [ ] Per-project approver restrictions
- [ ] Project templates
- [ ] Cross-project references

Each requires a separate ARCH document before implementation.

---

## 11. References

- `eve/core/trinity_api.py` — normalize_project_id(), v1.1.0
- `eve/core/knowledge_api.py` — project_id forward + filter
- `eve/core/artifact_api.py` — project_id forward + filter
- `tests/test_trinity_v2_sanity.py` — 24 tests
- `tests/test_v2_e2e_sanity.py` — 29 tests
- Commit: `27ce271` (eve-v2-verified)

---

## 12. Amendment Log

| Date | Change | By |
|------|--------|-----|
| 2026-02-02 | Initial version, locked | Joakim Eklund |

---

**END OF DOCUMENT**
