import { Project } from '../state/projectContext'

// ─── Mock Data ───────────────────────────────────────────
// Used when Trinity API is not available (mock-first development).
// Replace with real API calls when backend is running.

const USE_MOCK = true

const MOCK_PROJECTS: Project[] = [
  {
    project_id: "legacy",
    label: "Legacy (v1)",
    description: "Backward-compatible mode for existing decisions",
    created_at: "2026-01-01T00:00:00Z",
    status: "active",
    policy: null,
    license: null,
    sku: null,
  },
  {
    project_id: "compliedocs-core",
    label: "ComplieDocs",
    description: "B2B compliance documentation platform",
    created_at: "2026-01-15T10:00:00Z",
    status: "active",
    policy: null,
    license: null,
    sku: null,
  },
  {
    project_id: "medical-evidence",
    label: "Medical Evidence",
    description: "Ask EVE Medical — evidence verification",
    created_at: "2026-02-01T23:00:00Z",
    status: "active",
    policy: null,
    license: null,
    sku: null,
  },
  {
    project_id: "elekto-marina",
    label: "ELEKTO Marina",
    description: "Energy tokenization for marinas",
    created_at: "2026-01-20T08:00:00Z",
    status: "active",
    policy: null,
    license: null,
    sku: null,
  },
]

const BASE = "/api"

// ─── API Functions ───────────────────────────────────────

export async function listProjects(): Promise<Project[]> {
  if (USE_MOCK) return MOCK_PROJECTS

  const res = await fetch(`${BASE}/v1/projects`)
  if (!res.ok) throw new Error(`Failed to list projects: ${res.status}`)
  return res.json()
}

export async function createProject(
  project_id: string,
  label: string,
  description?: string
): Promise<Project> {
  if (USE_MOCK) {
    const p: Project = {
      project_id,
      label,
      description,
      created_at: new Date().toISOString(),
      status: "active",
      policy: null,
      license: null,
      sku: null,
    }
    MOCK_PROJECTS.push(p)
    return p
  }

  const res = await fetch(`${BASE}/v1/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id, label, description }),
  })
  if (!res.ok) throw new Error(`Failed to create project: ${res.status}`)
  return res.json()
}

export async function getProject(project_id: string): Promise<Project> {
  if (USE_MOCK) {
    const p = MOCK_PROJECTS.find(p => p.project_id === project_id)
    if (!p) throw new Error(`Project not found: ${project_id}`)
    return p
  }

  const res = await fetch(`${BASE}/v1/projects/${project_id}`)
  if (!res.ok) throw new Error(`Failed to get project: ${res.status}`)
  return res.json()
}
