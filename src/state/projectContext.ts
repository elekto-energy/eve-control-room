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

let currentProject: Project | null = null

export function setProject(p: Project) { currentProject = p }

export function requireProject(): Project {
  if (!currentProject) throw new Error("No project selected")
  return currentProject
}

export function getProject(): Project | null { return currentProject }
