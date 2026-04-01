import { Loader, RefreshCw, Terminal } from 'lucide-react'

import type { CurrentLogsResponse } from './types'

interface LiveLogsCardProps {
  logData: CurrentLogsResponse | undefined
  logsFetching: boolean
  showLogs: boolean
  onToggleLogs: () => void
  onRefreshLogs: () => void
}

export default function LiveLogsCard({
  logData,
  logsFetching,
  showLogs,
  onToggleLogs,
  onRefreshLogs,
}: LiveLogsCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Terminal className="h-5 w-5 text-gray-600 dark:text-gray-300" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Live Workflow Logs</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Real-time scanner output from the currently active block.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onToggleLogs}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            showLogs
              ? 'bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600'
              : 'bg-blue-100 text-blue-800 hover:bg-blue-200 dark:bg-blue-900/40 dark:text-blue-200 dark:hover:bg-blue-900/60'
          }`}
        >
          {showLogs ? 'Hide Logs' : 'Show Logs'}
        </button>
      </div>

      {showLogs && (
        <div className="mt-4">
          {logsFetching && !logData ? (
            <div className="flex items-center justify-center py-8">
              <Loader className="h-6 w-6 animate-spin text-blue-600" />
            </div>
          ) : logData?.status === 'not_running' ? (
            <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-400">
              Continuous ACO workflow is not running. Start it to see live logs.
            </div>
          ) : logData?.status === 'idle' ? (
            <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-400">
              {logData.message || 'No workflow currently running.'}
              {logData.last_error && <p className="mt-2 text-rose-600 dark:text-rose-400">Last error: {logData.last_error}</p>}
            </div>
          ) : logData?.logs ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                <span>
                  <span className="font-mono">{logData.scan?.cidr}</span>
                  {' — '}
                  <span className="font-mono">{logData.scan?.scan_uuid}</span>
                </span>
                <button
                  type="button"
                  onClick={onRefreshLogs}
                  className="flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${logsFetching ? 'animate-spin' : ''}`} />
                  Refresh
                </button>
              </div>
              <div className="max-h-[32rem] overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-100">
                <pre className="whitespace-pre-wrap break-words">{logData.logs}</pre>
              </div>
            </div>
          ) : (
            <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-400">
              Waiting for log output...
            </div>
          )}
        </div>
      )}
    </div>
  )
}
