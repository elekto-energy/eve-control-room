import { Project } from '../state/projectContext'

// ─── Configuration ───────────────────────────────────────
// Toggle between mock data and real API.
// Set to false when project_registry.py is running on port 8004.

const USE_MOCK = true
const API_BASE = "http://127.0.0.1:8000"

// ─── Mock Data (fallback) ────────────────────────────────
// Used when API is not available.

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
    label: "ComplieDocs – Compliance",
    description: "Regulatory compliance verification",
    created_at: "2026-01-15T10:00:00Z",
    status: "active",
    policy: null,
    license: null,
    sku: null,
  },
  {
    project_id: "medical-core",
    label: "Medical Evidence – Core",
    description: "Clinical-grade verified medical knowledge",
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

// ─── Legacy Fallback ─────────────────────────────────────
// Always available, even if API fails.

const LEGACY_PROJECT: Project = {
  project_id: "legacy",
  label: "Legacy (v1)",
  description: "Backward-compatible mode",
  created_at: "2026-01-01T00:00:00Z",
  status: "active",
  policy: null,
  license: null,
  sku: null,
}

// ─── API Response Types ──────────────────────────────────

type RegistryProject = {
  project_id: string
  label: string
  project_class: string
  trust_tier: string
  description?: string
  locked: boolean
}

type ProjectListResponse = {
  projects: RegistryProject[]
  count: number
}

// ─── Transform Registry → UI Model ───────────────────────

function transformProject(rp: RegistryProject): Project {
  return {
    project_id: rp.project_id,
    label: rp.label,
    description: rp.description,
    created_at: "2026-01-01T00:00:00Z", // Registry doesn't track this
    status: rp.locked ? "active" : "active",
    policy: null,
    license: null,
    sku: null,
  }
}

// ─── API Functions ───────────────────────────────────────

export async function listProjects(): Promise<Project[]> {
  if (USE_MOCK) {
    return MOCK_PROJECTS
  }

  try {
    const res = await fetch(`${API_BASE}/api/projects`)
    if (!res.ok) {
      console.warn(`Project Registry returned ${res.status}, using fallback`)
      return [LEGACY_PROJECT]
    }
    const data: ProjectListResponse = await res.json()
    return data.projects.map(transformProject)
  } catch (e) {
    console.warn("Project Registry unavailable, using fallback:", e)
    return [LEGACY_PROJECT]
  }
}

export async function getProject(project_id: string): Promise<Project> {
  if (USE_MOCK) {
    const p = MOCK_PROJECTS.find(p => p.project_id === project_id)
    if (!p) throw new Error(`Project not found: ${project_id}`)
    return p
  }

  try {
    const res = await fetch(`${API_BASE}/api/projects/${project_id}`)
    if (!res.ok) {
      if (project_id === "legacy") return LEGACY_PROJECT
      throw new Error(`Project not found: ${project_id}`)
    }
    const data: RegistryProject = await res.json()
    return transformProject(data)
  } catch (e) {
    if (project_id === "legacy") return LEGACY_PROJECT
    throw e
  }
}

// ─── Create Project (mock only) ──────────────────────────
// Project Registry is read-only. This is for mock development only.

export async function createProject(
  project_id: string,
  label: string,
  description?: string
): Promise<Project> {
  if (!USE_MOCK) {
    throw new Error("Project Registry is read-only. Projects must be added to projects.json.")
  }

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
