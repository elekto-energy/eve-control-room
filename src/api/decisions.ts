const BASE = "/api"

export type Decision = {
  eve_decision_id: string
  project_id: string
  hash_version: "v1" | "v2"
  payload_hash: string
  context_hash: string
  status: string
  created_at: string
}

// ─── Mock Data ───────────────────────────────────────────

const USE_MOCK = true

const MOCK_DECISIONS: Decision[] = [
  {
    eve_decision_id: "EVE-2026-000001",
    project_id: "compliedocs-core",
    hash_version: "v2",
    payload_hash: "a1b2c3d4e5f6...",
    context_hash: "f6e5d4c3b2a1...",
    status: "SEALED",
    created_at: "2026-02-01T12:00:00Z",
  },
  {
    eve_decision_id: "EVE-2026-000002",
    project_id: "medical-evidence",
    hash_version: "v2",
    payload_hash: "b2c3d4e5f6a1...",
    context_hash: "e5d4c3b2a1f6...",
    status: "PENDING_APPROVAL",
    created_at: "2026-02-02T08:00:00Z",
  },
]

// ─── API Functions ───────────────────────────────────────

export async function listDecisions(project_id: string): Promise<Decision[]> {
  if (USE_MOCK) return MOCK_DECISIONS.filter(d => d.project_id === project_id)

  const res = await fetch(`${BASE}/decisions?project_id=${project_id}`)
  if (!res.ok) throw new Error(`Failed to list decisions: ${res.status}`)
  return res.json()
}

export async function verifyDecision(eve_decision_id: string): Promise<{ status: string }> {
  if (USE_MOCK) return { status: "VERIFIED" }

  const res = await fetch(`${BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ eve_decision_id }),
  })
  if (!res.ok) throw new Error(`Verification failed: ${res.status}`)
  return res.json()
}
