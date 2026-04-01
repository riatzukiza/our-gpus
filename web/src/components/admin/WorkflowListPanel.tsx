import { formatAge, resultClasses } from './format'
import type { WorkflowResponse } from './types'

interface WorkflowListPanelProps {
  workflows: WorkflowResponse[]
  onSelect: (workflow: WorkflowResponse) => void
  selectedId: string | null
}

export default function WorkflowListPanel({ workflows, onSelect, selectedId }: WorkflowListPanelProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Workflows</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            All persisted workflow runs, both one-off and continuous.
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {workflows.length > 0 ? (
          workflows.map((workflow) => (
            <button
              key={workflow.workflow_id}
              type="button"
              onClick={() => onSelect(workflow)}
              className={`w-full rounded-xl border p-4 text-left transition-colors ${
                selectedId === workflow.workflow_id
                  ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-900/20'
                  : 'border-gray-200 bg-gray-50 hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900/40 dark:hover:border-gray-600'
              }`}
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-mono text-xs text-gray-500 dark:text-gray-400">
                      {workflow.workflow_id.slice(0, 8)}
                    </p>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${resultClasses(workflow.status === 'completed')}`}>
                      {workflow.status}
                    </span>
                  </div>
                  <p className="mt-2 font-medium text-gray-900 dark:text-white">
                    {workflow.strategy} on {workflow.target}
                  </p>
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Created {formatAge(workflow.created_at)}
                    {workflow.started_at && `, started ${formatAge(workflow.started_at)}`}
                  </p>
                </div>

                <div className="text-right text-sm">
                  <p className="text-gray-500 dark:text-gray-400">{workflow.workflow_kind}</p>
                  {workflow.summary && typeof workflow.summary.discovered_hosts === 'number' && (
                    <p className="mt-1 font-semibold text-gray-900 dark:text-white">
                      {workflow.summary.discovered_hosts} hosts
                    </p>
                  )}
                </div>
              </div>

              {workflow.last_error && (
                <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{workflow.last_error}</p>
              )}
            </button>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
            No workflows recorded yet. Run a one-off or continuous scan to create the first workflow.
          </div>
        )}
      </div>
    </div>
  )
}