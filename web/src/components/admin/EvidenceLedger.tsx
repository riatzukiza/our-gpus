import { formatAge } from './format'
import type { WorkflowDetailResponse, WorkflowReceiptResponse } from './types'

interface EvidenceLedgerProps {
  workflow: WorkflowDetailResponse
}

function StageReceiptCard({ receipt }: { receipt: WorkflowReceiptResponse }) {
  const isComplete = receipt.status === 'completed'
  const isRunning = receipt.status === 'running' || receipt.status === 'pending'
  const isFailed = receipt.status === 'failed'

  return (
    <div className={`border rounded-sm p-3 transition-colors
      ${isComplete
        ? 'border-gray-800 bg-gray-900/40'
        : isRunning
          ? 'border-green-900/50 bg-green-900/10'
          : isFailed
            ? 'border-rose-900/50 bg-rose-900/10'
            : 'border-gray-800 bg-gray-900/20'
      }
    `}>
      {/* Header */}
      <div className="flex justify-between items-start gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-gray-400">
            {receipt.stage_name}
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            {formatAge(receipt.started_at)}
            {receipt.finished_at && ` → ${formatAge(receipt.finished_at)}`}
          </div>
        </div>
        <span className={`
          rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide
          ${isComplete
            ? 'bg-emerald-500/20 text-emerald-400'
            : isRunning
              ? 'bg-amber-500/20 text-amber-400'
              : isFailed
                ? 'bg-rose-500/20 text-rose-400'
                : 'bg-gray-700 text-gray-400'
          }
        `}>
          {receipt.status}
        </span>
      </div>

      {/* Metrics */}
      {Object.keys(receipt.metrics).length > 0 && (
        <div className="mt-2 space-y-1">
          {Object.entries(receipt.metrics).map(([key, value]) => (
            <div key={key} className="flex justify-between text-[10px]">
              <span className="text-gray-500">{key.replace(/_/g, ' ')}</span>
              <span className="text-gray-200 font-mono">
                {typeof value === 'number' ? value.toLocaleString() : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Evidence References */}
      {receipt.evidence_refs.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-800">
          <div className="text-[10px] text-gray-500 mb-1">Evidence</div>
          <ul className="space-y-0.5">
            {receipt.evidence_refs.slice(0, 5).map((ref, idx) => (
              <li key={idx} className="truncate text-[10px] text-blue-400 font-mono">
                {ref}
              </li>
            ))}
            {receipt.evidence_refs.length > 5 && (
              <li className="text-[10px] text-gray-500">
                +{receipt.evidence_refs.length - 5} more
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Error */}
      {receipt.error && (
        <div className="mt-2 text-[10px] text-rose-400">
          {receipt.error}
        </div>
      )}
    </div>
  )
}

export default function EvidenceLedger({ workflow }: EvidenceLedgerProps) {
  return (
    <div className="h-full flex flex-col bg-[#050505]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex-shrink-0">
        <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-gray-500">
          Evidence Ledger
        </div>
        <div className="mt-1 text-sm text-gray-100 font-mono truncate">
          {workflow.workflow_kind} // {workflow.strategy}
        </div>
        <div className="mt-0.5 text-xs text-gray-400 font-mono truncate">
          {workflow.target}
        </div>
      </div>

      {/* Provenance */}
      <div className="px-4 py-2 border-b border-gray-800 flex-shrink-0">
        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div>
            <div className="text-gray-500">Policy</div>
            <div className="font-mono text-gray-300 truncate">
              {workflow.policy_snapshot_hash?.slice(0, 16) ?? '—'}...
            </div>
          </div>
          <div>
            <div className="text-gray-500">Exclusions</div>
            <div className="font-mono text-gray-300 truncate">
              {workflow.exclude_snapshot_hash?.slice(0, 16) ?? '—'}...
            </div>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      {workflow.summary && Object.keys(workflow.summary).length > 0 && (
        <div className="px-4 py-2 border-b border-gray-800 flex-shrink-0">
          <div className="flex gap-4 text-[11px]">
            {typeof workflow.summary.discovered_hosts === 'number' && (
              <div>
                <span className="text-gray-500">Hosts: </span>
                <span className="text-gray-200 font-mono">
                  {workflow.summary.discovered_hosts.toLocaleString()}
                </span>
              </div>
            )}
            {typeof workflow.summary.probes_sent === 'number' && (
              <div>
                <span className="text-gray-500">Probes: </span>
                <span className="text-gray-200 font-mono">
                  {workflow.summary.probes_sent.toLocaleString()}
                </span>
              </div>
            )}
            {typeof workflow.summary.success_count === 'number' && (
              <div>
                <span className="text-gray-500">OK: </span>
                <span className="text-emerald-400 font-mono">
                  {workflow.summary.success_count.toLocaleString()}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Stage Receipts */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">
          Stage Receipts
        </div>

        {workflow.receipts.length > 0 ? (
          workflow.receipts.map((receipt) => (
            <StageReceiptCard key={receipt.receipt_id} receipt={receipt} />
          ))
        ) : (
          <div className="rounded-sm border border-dashed border-gray-800 p-4 text-center">
            <p className="text-xs text-gray-500 font-mono">No receipts yet</p>
            <p className="mt-1 text-[10px] text-gray-600">
              Stage execution will appear here
            </p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-gray-800 flex-shrink-0">
        <div className="text-[10px] text-gray-600 space-y-0.5">
          <div>Created: {workflow.created_at}</div>
          {workflow.started_at && <div>Started: {workflow.started_at}</div>}
          {workflow.completed_at && <div>Completed: {workflow.completed_at}</div>}
        </div>
      </div>
    </div>
  )
}