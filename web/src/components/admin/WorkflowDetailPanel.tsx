import { formatAge } from './format'
import type { WorkflowDetailResponse, WorkflowReceiptResponse } from './types'

interface WorkflowDetailPanelProps {
  workflow: WorkflowDetailResponse
  onClose: () => void
}

function ReceiptCard({ receipt }: { receipt: WorkflowReceiptResponse }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-gray-900 dark:text-white">{receipt.stage_name}</p>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {formatAge(receipt.started_at)}
            {receipt.finished_at && `, finished ${formatAge(receipt.finished_at)}`}
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            receipt.status === 'completed'
              ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
              : receipt.status === 'failed'
                ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200'
                : 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
          }`}
        >
          {receipt.status}
        </span>
      </div>

      {Object.keys(receipt.metrics).length > 0 && (
        <div className="mt-3 space-y-1">
          {Object.entries(receipt.metrics).map(([key, value]) => (
            <p key={key} className="text-sm text-gray-600 dark:text-gray-300">
              {key}: {typeof value === 'number' ? value.toLocaleString() : String(value)}
            </p>
          ))}
        </div>
      )}

      {receipt.error && <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{receipt.error}</p>}

      {receipt.evidence_refs.length > 0 && (
        <div className="mt-3 space-y-1">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Evidence</p>
          {receipt.evidence_refs.map((ref, idx) => (
            <p key={idx} className="font-mono text-xs text-gray-400 dark:text-gray-500">
              {ref}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function WorkflowDetailPanel({ workflow, onClose }: WorkflowDetailPanelProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Workflow {workflow.workflow_id.slice(0, 8)}</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {workflow.workflow_kind} • {workflow.strategy} • port {workflow.port}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
        >
          Close
        </button>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Target</p>
          <p className="mt-1 font-mono text-sm text-gray-900 dark:text-white">{workflow.target}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Kind</p>
          <p className="mt-1 text-sm text-gray-900 dark:text-white">{workflow.workflow_kind}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Status</p>
          <p className="mt-1 text-sm text-gray-900 dark:text-white">{workflow.status}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Stage</p>
          <p className="mt-1 text-sm text-gray-900 dark:text-white">{workflow.current_stage || '—'}</p>
        </div>
      </div>

      {workflow.summary && Object.keys(workflow.summary).length > 0 && (
        <div className="mt-6">
          <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Summary</h4>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(workflow.summary).map(([key, value]) => (
              <div
                key={key}
                className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-900/40"
              >
                <p className="text-xs text-gray-500 dark:text-gray-400">{key.replace(/_/g, ' ')}</p>
                <p className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
                  {typeof value === 'number' ? value.toLocaleString() : String(value)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {workflow.last_error && (
        <div className="mt-6 rounded-lg border border-rose-200 bg-rose-50 p-4 dark:border-rose-800 dark:bg-rose-900/20">
          <p className="text-sm font-medium text-rose-800 dark:text-rose-200">Error</p>
          <p className="mt-1 text-sm text-rose-700 dark:text-rose-300">{workflow.last_error}</p>
        </div>
      )}

      <div className="mt-6">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Stage Receipts</h4>
        <div className="mt-3 space-y-3">
          {workflow.receipts.length > 0 ? (
            workflow.receipts.map((receipt) => <ReceiptCard key={receipt.receipt_id} receipt={receipt} />)
          ) : (
            <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
              No stage receipts recorded yet.
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 space-y-2 text-xs text-gray-500 dark:text-gray-400">
        <p>Created: {workflow.created_at}</p>
        {workflow.started_at && <p>Started: {workflow.started_at}</p>}
        {workflow.completed_at && <p>Completed: {workflow.completed_at}</p>}
        {workflow.exclude_snapshot_hash && (
          <p className="font-mono">Exclude snapshot: {workflow.exclude_snapshot_hash.slice(0, 16)}...</p>
        )}
      </div>
    </div>
  )
}