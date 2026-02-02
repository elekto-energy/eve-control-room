import { useEffect, useState } from 'react'
import { Decision, listDecisions, verifyDecision } from '../api/decisions'

type Props = {
  project_id: string
}

export function DecisionList({ project_id }: Props) {
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    listDecisions(project_id)
      .then(setDecisions)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [project_id])

  if (loading) return <p className="text-slate-400">Loading decisions...</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (decisions.length === 0) {
    return <p className="text-slate-500">No decisions found for this project.</p>
  }

  return (
    <div className="space-y-3">
      {decisions.map(d => (
        <DecisionCard key={d.eve_decision_id} decision={d} />
      ))}
    </div>
  )
}

function DecisionCard({ decision }: { decision: Decision }) {
  const [verifyStatus, setVerifyStatus] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)

  const handleVerify = async () => {
    setVerifying(true)
    try {
      const result = await verifyDecision(decision.eve_decision_id)
      setVerifyStatus(result.status)
    } catch {
      setVerifyStatus("FAILED")
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className="rounded-lg bg-slate-800 border border-slate-700 p-4">
      {/* Header row */}
      <div className="flex justify-between items-start mb-3">
        <div>
          <span className="font-mono text-sm text-white">{decision.eve_decision_id}</span>
          <span className={`ml-2 text-xs px-2 py-0.5 rounded ${
            decision.status === 'SEALED'
              ? 'bg-green-900 text-green-300'
              : decision.status === 'PENDING_APPROVAL'
              ? 'bg-yellow-900 text-yellow-300'
              : 'bg-slate-600 text-slate-300'
          }`}>
            {decision.status}
          </span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded font-mono ${
          decision.hash_version === 'v2'
            ? 'bg-blue-900 text-blue-300'
            : 'bg-slate-600 text-slate-400'
        }`}>
          {decision.hash_version}
        </span>
      </div>

      {/* Hash fields — read-only, no interpretation */}
      <div className="space-y-2 text-sm">
        <HashRow label="payload_hash" value={decision.payload_hash} />
        <HashRow label="context_hash" value={decision.context_hash} />
        <HashRow label="project_id" value={decision.project_id} />
        <div className="flex justify-between">
          <span className="text-slate-500">created_at</span>
          <span className="text-slate-300">{new Date(decision.created_at).toLocaleString()}</span>
        </div>
      </div>

      {/* Verify button — delegates to API, never interprets */}
      <div className="mt-3 pt-3 border-t border-slate-700 flex items-center justify-between">
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-50 transition-colors"
        >
          {verifying ? 'Verifying...' : 'Verify'}
        </button>
        {verifyStatus && (
          <span className={`text-xs font-mono ${
            verifyStatus === 'VERIFIED' ? 'text-green-400' : 'text-red-400'
          }`}>
            {verifyStatus}
          </span>
        )}
      </div>
    </div>
  )
}

function HashRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300 font-mono text-xs">{value}</span>
    </div>
  )
}
