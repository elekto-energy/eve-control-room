import { requireProject } from "../state/projectContext"

const BASE = "http://127.0.0.1:8000"

export async function listProjects() {
  const res = await fetch(BASE + "/api/v1/projects")
  return res.json()
}

export async function createProject(project_id: string, label: string) {
  const res = await fetch(BASE + "/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id, label })
  })
  return res.json()
}
