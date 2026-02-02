// ─── Project Model ───────────────────────────────────────
// Canonical type. Packaging hooks MUST exist, MUST be null.

export type Project = {
  project_id: string
  label: string
  description?: string
  created_at: string
  status: "active" | "archived"
  policy: null
  license: null
  sku: null
}

// ─── Context ─────────────────────────────────────────────
// Single source of truth with session persistence.

const STORAGE_KEY = "eve_project_id"

let currentProject: Project | null = null

export function setProject(p: Project) {
  currentProject = p
  sessionStorage.setItem(STORAGE_KEY, p.project_id)
}

export function requireProject(): Project {
  if (!currentProject) throw new Error("No project selected — cannot proceed")
  return currentProject
}

export function getProject(): Project | null { return currentProject }

export function getProjectId(): string {
  return currentProject?.project_id ?? "legacy"
}

export function loadProjectIdFromSession(): string | null {
  return sessionStorage.getItem(STORAGE_KEY)
}

export function clearProject() {
  currentProject = null
  sessionStorage.removeItem(STORAGE_KEY)
}
