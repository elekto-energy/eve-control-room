#!/usr/bin/env python3
"""
Project Registry Tests
======================
Validates read-only project registry behavior.

© 2026 Organiq Sweden AB
"""

import sys
import os
import json

sys.path.insert(0, "D:/EVE11/Projects/006_github_repos/eve-control-room/eve/core")
os.environ["CAS_PROBE_DISABLED"] = "1"

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1


def section(title):
    print(f"\n{'─' * 60}")
    print(f"🧪 {title}")
    print('─' * 60)


print("=" * 60)
print("EVE PROJECT REGISTRY TESTS")
print("=" * 60)

# ═══════════════════════════════════════════════════════════════
# TEST 1: Load projects.json
# ═══════════════════════════════════════════════════════════════

section("Test 1: Load projects.json")

from project_registry import load_projects, get_project_metadata, PROJECTS_FILE

test("projects.json exists", PROJECTS_FILE.exists(), str(PROJECTS_FILE))

projects = load_projects()
test("Projects loaded as list", isinstance(projects, list))
test("At least 1 project", len(projects) >= 1)

# ═══════════════════════════════════════════════════════════════
# TEST 2: Legacy project required
# ═══════════════════════════════════════════════════════════════

section("Test 2: Legacy project required")

legacy = get_project_metadata("legacy")
test("Legacy project exists", legacy is not None)
test("Legacy project_id correct", legacy.get("project_id") == "legacy")
test("Legacy is locked", legacy.get("locked") == True)

# ═══════════════════════════════════════════════════════════════
# TEST 3: No duplicate project_ids
# ═══════════════════════════════════════════════════════════════

section("Test 3: No duplicate project_ids")

ids = [p.get("project_id") for p in projects]
unique_ids = set(ids)
test("All project_ids unique", len(ids) == len(unique_ids), f"duplicates: {len(ids) - len(unique_ids)}")

# ═══════════════════════════════════════════════════════════════
# TEST 4: Required fields
# ═══════════════════════════════════════════════════════════════

section("Test 4: Required fields present")

required_fields = ["project_id", "label", "project_class", "trust_tier"]

for p in projects:
    pid = p.get("project_id", "unknown")
    for field in required_fields:
        test(f"{pid}: has '{field}'", field in p, f"missing in {pid}")

# ═══════════════════════════════════════════════════════════════
# TEST 5: Get single project
# ═══════════════════════════════════════════════════════════════

section("Test 5: Get single project")

compliedocs = get_project_metadata("compliedocs-core")
test("compliedocs-core found", compliedocs is not None)
test("compliedocs-core label", compliedocs.get("label") == "ComplieDocs – Compliance" if compliedocs else False)

nonexistent = get_project_metadata("does-not-exist")
test("Nonexistent returns None", nonexistent is None)

# ═══════════════════════════════════════════════════════════════
# TEST 6: Pydantic models
# ═══════════════════════════════════════════════════════════════

section("Test 6: Pydantic models")

from project_registry import ProjectMetadata, ProjectListResponse

# Valid project
pm = ProjectMetadata(
    project_id="test",
    label="Test Project",
    project_class="custom",
    trust_tier="T1"
)
test("ProjectMetadata instantiates", pm.project_id == "test")

# List response
plr = ProjectListResponse(
    projects=[pm],
    count=1
)
test("ProjectListResponse instantiates", plr.count == 1)

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("🟢 ALL TESTS PASSED — Project Registry verified")
else:
    print("🔴 FAILURES DETECTED — Review before proceeding")
print("=" * 60)
