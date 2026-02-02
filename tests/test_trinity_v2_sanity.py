#!/usr/bin/env python3
"""
Trinity v2 Sanity Tests
=======================
Tests normalize_project_id + hash isolation.
Runs offline — no server needed.

© 2026 Organiq Sweden AB
"""

import sys
import json
import hashlib
import os

os.environ["CAS_PROBE_DISABLED"] = "1"
sys.path.insert(0, "D:/EVE11/Projects/006_github_repos/eve-control-room/eve/core")

from trinity_api import normalize_project_id, PROJECT_ID_REGEX

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


print("=" * 60)
print("TRINITY v2 SANITY TESTS")
print("=" * 60)

# TEST 1: v1 backward compatibility
print("\n🧪 Test 1: v1 backward compatibility (no project_id)")

pid, hv = normalize_project_id(None)
test("None → legacy", pid == "legacy", f"got {pid}")
test("None → v1", hv == "v1", f"got {hv}")

pid, hv = normalize_project_id("")
test("Empty → legacy", pid == "legacy", f"got {pid}")
test("Empty → v1", hv == "v1", f"got {hv}")

# TEST 2: v2 behavior
print("\n🧪 Test 2: v2 behavior (explicit project_id)")

pid, hv = normalize_project_id("medical-core")
test("medical-core → medical-core", pid == "medical-core", f"got {pid}")
test("medical-core → v2", hv == "v2", f"got {hv}")

pid, hv = normalize_project_id("compliedocs-core")
test("compliedocs-core → v2", hv == "v2", f"got {hv}")

# TEST 3: legacy is NOT reserved
print("\n🧪 Test 3: 'legacy' is allowed as explicit project_id")

pid, hv = normalize_project_id("legacy")
test("legacy explicit → legacy", pid == "legacy", f"got {pid}")
test("legacy explicit → v2", hv == "v2", f"got {hv}")

# TEST 4: Invalid project_ids fail hard
print("\n🧪 Test 4: Invalid project_ids → ValueError")

invalid_ids = [
    "UPPER", "has spaces", "-starts-dash",
    "ends-dash-", "a", "special!chars", "under_score",
]
for bad_id in invalid_ids:
    try:
        normalize_project_id(bad_id)
        test(f"'{bad_id}' should fail", False, "no error raised")
    except ValueError:
        test(f"'{bad_id}' → ValueError", True)

# TEST 5: Hash isolation
print("\n🧪 Test 5: Hash isolation")

def compute_context_hash(project_id_input):
    pid, hv = normalize_project_id(project_id_input)
    context_data = json.dumps({
        "project_id": pid,
        "system_id": "test-sys",
        "use_case": "test",
        "artifacts": ["CDOC-SCOPE-001"],
        "risk_links": None,
        "signoff": [{"role": "Compliance Owner", "actor_id": "joakim"}]
    }, sort_keys=True)
    return hashlib.sha256(context_data.encode()).hexdigest(), hv

hash_a, hv_a = compute_context_hash("project-alpha")
hash_b, hv_b = compute_context_hash("project-beta")
hash_legacy, hv_legacy = compute_context_hash(None)

test("alpha != beta", hash_a != hash_b)
test("alpha != legacy", hash_a != hash_legacy)
test("alpha = v2", hv_a == "v2")
test("legacy = v1", hv_legacy == "v1")

hash_a2, _ = compute_context_hash("project-alpha")
test("Deterministic: same input → same hash", hash_a == hash_a2)

# TEST 6: Regex boundaries
print("\n🧪 Test 6: Regex boundary checks")

pid, hv = normalize_project_id("a1")
test("a1 (min valid 2 chars) → v2", hv == "v2")

pid, hv = normalize_project_id("a" * 64)
test("64 chars (max) → v2", hv == "v2")

try:
    normalize_project_id("a" * 65)
    test("65 chars should fail", False, "no error")
except ValueError:
    test("65 chars → ValueError", True)

# SUMMARY
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("🟢 ALL TESTS PASSED")
else:
    print("🔴 FAILURES DETECTED")
print("=" * 60)
