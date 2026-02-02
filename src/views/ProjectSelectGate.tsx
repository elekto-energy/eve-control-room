import { useEffect, useState } from 'react'
import { Project } from '../state/projectContext'
import { listProjects, createProject } from '../api/projects'

type Props = {
  onSelect: (p: Project) => void
}

export function ProjectSelectGate({ onSelect }: Props) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-slate-400">Loading projects...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-red-400">Error: {error}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-lg w-full">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-white mb-2">EVE Control Room</h1>
          <p className="text-slate-400">Select a project to continue</p>
        </div>

        <div className="space-y-3">
          {projects.map(p => (
            <button
              key={p.project_id}
              onClick={() => onSelect(p)}
              className="w-full text-left p-4 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-500 transition-colors"
            >
              <div className="flex justify-between items-center">
                <div>
                  <div className="font-semibold text-white">{p.label}</div>
                  <div className="text-sm text-slate-400 font-mono">{p.project_id}</div>
                  {p.description && (
                    <div className="text-sm text-slate-500 mt-1">{p.description}</div>
                  )}
                </div>
                <span className={`text-xs px-2 py-1 rounded ${
                  p.status === 'active'
                    ? 'bg-green-900 text-green-300'
                    : 'bg-slate-600 text-slate-300'
                }`}>
                  {p.status}
                </span>
              </div>
            </button>
          ))}
        </div>

        <div className="mt-6">
          {showCreate ? (
            <CreateProjectForm
              onCreate={async (id, label, desc) => {
                const p = await createProject(id, label, desc)
                setProjects([...projects, p])
                setShowCreate(false)
              }}
              onCancel={() => setShowCreate(false)}
            />
          ) : (
            <button
              onClick={() => setShowCreate(true)}
              className="w-full p-3 rounded-lg border border-dashed border-slate-600 text-slate-400 hover:text-white hover:border-slate-400 transition-colors"
            >
              + Create new project
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Create Form ─────────────────────────────────────────

function CreateProjectForm({ onCreate, onCancel }: {
  onCreate: (id: string, label: string, desc?: string) => Promise<void>
  onCancel: () => void
}) {
  const [id, setId] = useState('')
  const [label, setLabel] = useState('')
  const [desc, setDesc] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const ID_REGEX = /^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$/

  const handleSubmit = async () => {
    setError(null)

    if (!ID_REGEX.test(id)) {
      setError('Invalid project_id: lowercase, digits, hyphens. Min 2 chars. No leading/trailing hyphen.')
      return
    }
    if (id === 'legacy') {
      setError('"legacy" is reserved and cannot be used.')
      return
    }
    if (!label.trim()) {
      setError('Label is required.')
      return
    }

    setSaving(true)
    try {
      await onCreate(id, label.trim(), desc.trim() || undefined)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create project')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-4 rounded-lg bg-slate-800 border border-slate-600 space-y-3">
      <div>
        <label className="block text-sm text-slate-400 mb-1">Project ID</label>
        <input
          value={id}
          onChange={e => setId(e.target.value.toLowerCase())}
          placeholder="my-project"
          className="w-full p-2 rounded bg-slate-900 border border-slate-600 text-white font-mono text-sm focus:border-blue-500 focus:outline-none"
        />
        <p className="text-xs text-slate-600 mt-1">Lowercase letters, numbers and hyphens only. Immutable after creation.</p>
      </div>
      <div>
        <label className="block text-sm text-slate-400 mb-1">Label</label>
        <input
          value={label}
          onChange={e => setLabel(e.target.value)}
          placeholder="My Project"
          className="w-full p-2 rounded bg-slate-900 border border-slate-600 text-white text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div>
        <label className="block text-sm text-slate-400 mb-1">Description (optional)</label>
        <input
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="Brief description"
          className="w-full p-2 rounded bg-slate-900 border border-slate-600 text-white text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex gap-2">
        <button
          onClick={handleSubmit}
          disabled={saving}
          className="flex-1 p-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium disabled:opacity-50"
        >
          {saving ? 'Creating...' : 'Create'}
        </button>
        <button
          onClick={onCancel}
          className="p-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
