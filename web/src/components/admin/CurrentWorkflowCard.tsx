import { Clock3 } from 'lucide-react'

import { formatAge, formatTimestamp, formatSeconds } from './format'
import type { CurrentJob } from './types'

interface CurrentWorkflowCardProps {
  currentJob: CurrentJob | null | undefined
}

export default function CurrentWorkflowCard({ currentJob }: CurrentWorkflowCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start gap-3">
        <Clock3 className="mt-1 h-5 w-5 text-blue-600 dark:text-blue-300" />
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Current Workflow Job</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            The block currently being scanned by the continuous ACO workflow, if it is active.
          </p>
        </div>
      </div>

      {currentJob ? (
        <div className="mt-5 space-y-4">
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-900/20">
            <p className="text-xs uppercase tracking-wide text-blue-700 dark:text-blue-200">Active Block</p>
            <p className="mt-2 text-2xl font-semibold text-blue-900 dark:text-blue-100">{currentJob.cidr}</p>
            <p className="mt-2 text-sm text-blue-700 dark:text-blue-200">
              Started {formatAge(currentJob.started_at)} and capped at about {formatSeconds(currentJob.estimated_duration_s)}.
            </p>
          </div>
          <dl className="space-y-3 text-sm text-gray-600 dark:text-gray-300">
            <div className="flex items-center justify-between gap-3">
              <dt>Scan UUID</dt>
              <dd className="font-mono">{currentJob.scan_uuid}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt>Started At</dt>
              <dd className="font-mono">{formatTimestamp(currentJob.started_at)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt>Output File</dt>
              <dd className="max-w-[16rem] truncate font-mono">{currentJob.output_file}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt>Log File</dt>
              <dd className="max-w-[16rem] truncate font-mono">{currentJob.log_file}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <div className="mt-5 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
          No block is currently being scanned.
        </div>
      )}
    </div>
  )
}
