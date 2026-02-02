import { useState, useEffect } from 'react'
import { ProjectSelectGate } from './views/ProjectSelectGate'
import { Dashboard } from './views/Dashboard'
import { Project, setProject as setContextProject, loadProjectIdFromSession } from './state/projectContext'
import { getProject } from './api/projects'

export function App() {
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)

  // Restore project from session on mount
  useEffect(() => {
    const savedId = loadProjectIdFromSession()
    if (savedId && savedId !== 'legacy') {
      getProject(savedId)
        .then(p => {
          setProject(p)
          setContextProject(p)
        })
        .catch(() => {
          // Project not found, clear and show gate
          setLoading(false)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const handleSelect = (p: Project) => {
    setProject(p)
    setContextProject(p)
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <p className="text-slate-400">Loading...</p>
      </div>
    )
  }

  if (!project) {
    return <ProjectSelectGate onSelect={handleSelect} />
  }

  return <Dashboard project={project} onSwitch={() => setProject(null)} />
}
