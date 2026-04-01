import { numberFormatter } from './format'
import type { ProbeStatsResponse } from './types'

interface ProbeSnapshotCardProps {
  probeStats: ProbeStatsResponse | undefined
  onRefresh: () => void
}

export default function ProbeSnapshotCard({ probeStats, onRefresh }: ProbeSnapshotCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Probe Snapshot</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Recent workflow outcomes from the last five minutes and current host status distribution.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          Refresh
        </button>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-4">
        <div className="rounded-xl bg-gray-50 p-4 dark:bg-gray-900/40">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Completed</p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">{numberFormatter.format(probeStats?.probes_completed || 0)}</p>
        </div>
        <div className="rounded-xl bg-emerald-50 p-4 dark:bg-emerald-900/20">
          <p className="text-xs uppercase tracking-wide text-emerald-700 dark:text-emerald-200">Success</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-900 dark:text-emerald-100">{numberFormatter.format(probeStats?.success_count || 0)}</p>
        </div>
        <div className="rounded-xl bg-amber-50 p-4 dark:bg-amber-900/20">
          <p className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-200">Timeout</p>
          <p className="mt-2 text-2xl font-semibold text-amber-900 dark:text-amber-100">{numberFormatter.format(probeStats?.timeout_count || 0)}</p>
        </div>
        <div className="rounded-xl bg-rose-50 p-4 dark:bg-rose-900/20">
          <p className="text-xs uppercase tracking-wide text-rose-700 dark:text-rose-200">Errors</p>
          <p className="mt-2 text-2xl font-semibold text-rose-900 dark:text-rose-100">{numberFormatter.format(probeStats?.error_count || 0)}</p>
        </div>
      </div>

      <div className="mt-5 space-y-3 text-sm text-gray-600 dark:text-gray-300">
        {Object.entries(probeStats?.host_status_breakdown || {}).map(([statusName, count]) => (
          <div key={statusName} className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-900/40">
            <span className="capitalize">{statusName.replace('_', ' ')}</span>
            <span className="font-mono">{numberFormatter.format(count)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
