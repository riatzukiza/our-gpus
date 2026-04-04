import { formatAge } from './format'
import type { WorkflowResponse } from './types'

interface WorkflowRailProps {
  workflows: WorkflowResponse[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export default function WorkflowRail({ workflows, selectedId, onSelect }: WorkflowRailProps) {
  return (
    <div className="h-full flex flex-col bg-[#050505]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex-shrink-0">
        <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-gray-500">
          Workflows
        </div>
        <div className="mt-1 text-xs text-gray-400">
          {workflows.length} total
        </div>
      </div>

      {/* Workflow List */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-900">
        {workflows.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <p className="text-xs text-gray-500 font-mono">No workflows yet</p>
            <p className="mt-1 text-[10px] text-gray-600">
              Run a scan to create your first workflow
            </p>
          </div>
        ) : (
          workflows.map((workflow) => {
            const isSelected = workflow.workflow_id === selectedId
            const isRunning = workflow.status === 'running' || workflow.status === 'pending'
            const isComplete = workflow.status === 'completed'
            const isFailed = workflow.status === 'failed'

            return (
              <button
                key={workflow.workflow_id}
                type="button"
                onClick={() => onSelect(workflow.workflow_id)}
                className={`w-full text-left px-4 py-3 font-mono text-xs transition-colors
                  ${isSelected
                    ? 'bg-green-900/15 border-l-2 border-l-green-500'
                    : 'hover:bg-gray-900/50'
                  }
                `}
              >
                {/* Strategy and Target */}
                <div className="flex justify-between gap-2">
                  <span className="truncate text-gray-300">
                    {workflow.strategy} // {workflow.target}
                  </span>
                  <span className={`
                    rounded-full px-2 py-0.5 text-[10px] font-medium flex-shrink-0
                    ${isRunning
                      ? 'bg-amber-500/20 text-amber-400'
                      : isComplete
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : isFailed
                          ? 'bg-rose-500/20 text-rose-400'
                          : 'bg-gray-700 text-gray-400'
                    }
                  `}>
                    {workflow.status}
                  </span>
                </div>

                {/* Stage and Time */}
                <div className="mt-1 flex justify-between text-[10px] text-gray-500">
                  <span>{workflow.current_stage ?? 'idle'}</span>
                  <span>{formatAge(workflow.created_at)}</span>
                </div>

                {/* Summary Stats */}
                {workflow.summary && typeof workflow.summary.discovered_hosts === 'number' && (
                  <div className="mt-2 flex gap-3 text-[10px]">
                    <span className="text-gray-400">
                      <span className="text-gray-500">hosts:</span> {workflow.summary.discovered_hosts.toLocaleString()}
                    </span>
                    {typeof workflow.summary.probes_sent === 'number' && (
                      <span className="text-gray-400">
                        <span className="text-gray-500">probes:</span> {workflow.summary.probes_sent.toLocaleString()}
                      </span>
                    )}
                  </div>
                )}

                {/* Error */}
                {workflow.last_error && (
                  <div className="mt-1 text-[10px] text-rose-400 truncate">
                    {workflow.last_error}
                  </div>
                )}
              </button>
            )
          })
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-gray-800 flex-shrink-0">
        <p className="text-[10px] text-gray-600 font-mono">
          Click a workflow to inspect
        </p>
      </div>
    </div>
  )
}