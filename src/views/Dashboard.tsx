import { Project } from '../state/projectContext'
import { DecisionList } from './DecisionList'

type Props = {
  project: Project
  onSwitch: () => void
}

export function Dashboard({ project, onSwitch }: Props) {
  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-slate-700 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-white">EVE Control Room</h1>
          <span className="text-sm text-slate-400">│</span>
          <div>
            <span className="text-sm font-medium text-blue-400">{project.label}</span>
            <span className="text-xs text-slate-500 ml-2 font-mono">{project.project_id}</span>
          </div>
        </div>
        <button
          onClick={onSwitch}
          className="text-sm text-slate-400 hover:text-white transition-colors"
        >
          Switch project
        </button>
      </header>

      {/* Content */}
      <main className="p-6 max-w-4xl mx-auto">
        {/* Project metadata */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard label="Project ID" value={project.project_id} mono />
          <StatCard label="Status" value={project.status} />
          <StatCard label="Created" value={new Date(project.created_at).toLocaleDateString()} />
        </div>

        {project.description && (
          <p className="text-slate-400 mb-8">{project.description}</p>
        )}

        {/* Packaging hooks — visible but null */}
        <div className="rounded-lg bg-slate-800 border border-slate-700 p-4 mb-8">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Packaging Hooks</h2>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <HookField label="policy" />
            <HookField label="license" />
            <HookField label="sku" />
          </div>
        </div>

        {/* Decisions */}
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Decisions</h2>
          <DecisionList project_id={project.project_id} />
        </div>
      </main>
    </div>
  )
}

function StatCard({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg bg-slate-800 border border-slate-700 p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-sm text-white ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  )
}

function HookField({ label }: { label: string }) {
  return (
    <div>
      <span className="text-slate-500">{label}</span>
      <span className="ml-2 text-slate-600 font-mono">null</span>
    </div>
  )
}
