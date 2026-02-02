import { requireProject } from "../state/projectContext"

const BASE = "http://127.0.0.1:8000"

export async function listDecisions() {
  const p = requireProject()
  const res = await fetch(BASE + "/decisions?project_id=" + p.project_id)
  return res.json()
}

export async function getDecision(id: string) {
  const res = await fetch(BASE + "/decision/" + id)
  return res.json()
}

export async function verifyDecision(id: string) {
  const res = await fetch(BASE + "/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ eve_decision_id: id })
  })
  return res.json()
}
