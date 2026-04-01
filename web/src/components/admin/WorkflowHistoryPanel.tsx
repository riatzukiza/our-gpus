import { formatAge, formatDurationMs, numberFormatter, resultClasses } from './format'
import type { HistoryEntry, RecentResult, TopBlock } from './types'

interface WorkflowHistoryPanelProps {
  recentResults: RecentResult[]
  topBlocks: TopBlock[]
  history: HistoryEntry[]
}

export default function WorkflowHistoryPanel({ recentResults, topBlocks, history }: WorkflowHistoryPanelProps) {
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Workflow Runs</h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              Recent block-level workflow runs from the in-process scheduler.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
            {numberFormatter.format(recentResults.length)} results
          </span>
        </div>

        <div className="mt-5 space-y-3">
          {recentResults.length > 0 ? (
            recentResults.map((result) => (
              <div key={`${result.scan_uuid}-${result.completed_at}`} className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-gray-900 dark:text-white">{result.cidr}</p>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${resultClasses(result.success)}`}>
                        {result.success ? 'completed' : 'failed'}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                      Finished {formatAge(result.completed_at)} after {formatDurationMs(result.duration_ms)}.
                    </p>
                  </div>

                  <div className="text-right text-sm">
                    <p className="font-semibold text-gray-900 dark:text-white">{numberFormatter.format(result.hosts_found)} hosts</p>
                    <p className="text-gray-500 dark:text-gray-400">{result.scan_uuid}</p>
                  </div>
                </div>

                {result.error && <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{result.error}</p>}
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
              No live workflow runs yet.
            </div>
          )}
        </div>

        <div className="mt-6 rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Persisted ACO Ingest History</h4>
          <div className="mt-4 space-y-3">
            {history.length > 0 ? (
              history.slice(0, 10).map((entry) => (
                <div key={entry.scan_id} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-gray-900 dark:text-white">{entry.cidr || `scan #${entry.scan_id}`}</p>
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                          {entry.status}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                        Started {formatAge(entry.started_at)} and recorded {numberFormatter.format(entry.hosts_found)} hosts.
                      </p>
                    </div>
                  </div>
                  {entry.error_message && <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{entry.error_message}</p>}
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
                No ACO block ingests have been recorded yet.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Top Candidate Blocks</h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Highest-pheromone blocks the ACO engine is currently favoring.
        </p>

        <div className="mt-5 space-y-3">
          {topBlocks.length > 0 ? (
            topBlocks.slice(0, 8).map((block) => (
              <div key={block.cidr} className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-mono text-sm font-medium text-gray-900 dark:text-white">{block.cidr}</p>
                  <p className="text-sm font-semibold text-blue-600 dark:text-blue-300">{block.pheromone.toFixed(3)}</p>
                </div>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  {numberFormatter.format(block.cumulative_yield)} hosts over {numberFormatter.format(block.scan_count)} scans.
                </p>
                <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">Last scan: {formatAge(block.last_scan)}</p>
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
              Start the scheduler to build block rankings.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
