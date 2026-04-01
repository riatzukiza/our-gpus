import { formatAge, formatProgressPercent, formatTimestamp, getJobCounts, jobStatusClasses, numberFormatter } from './format'
import type { AdminJobsResponse } from './types'

interface JobsPanelProps {
  workers: AdminJobsResponse['workers'] | undefined
  jobs: AdminJobsResponse['jobs']
  onRefresh: () => void
}

export default function JobsPanel({ workers, jobs, onRefresh }: JobsPanelProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Jobs</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Individual Celery jobs still show up here, but the shared workflow panel above is the preferred way to start work.
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

      <div className="mt-5 grid gap-3 sm:grid-cols-4">
        <div className="rounded-xl bg-gray-50 p-4 dark:bg-gray-900/40">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Workers</p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">{numberFormatter.format(workers?.totals.workers || 0)}</p>
        </div>
        <div className="rounded-xl bg-blue-50 p-4 dark:bg-blue-900/20">
          <p className="text-xs uppercase tracking-wide text-blue-700 dark:text-blue-200">Active</p>
          <p className="mt-2 text-2xl font-semibold text-blue-900 dark:text-blue-100">{numberFormatter.format(workers?.totals.active || 0)}</p>
        </div>
        <div className="rounded-xl bg-amber-50 p-4 dark:bg-amber-900/20">
          <p className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-200">Reserved</p>
          <p className="mt-2 text-2xl font-semibold text-amber-900 dark:text-amber-100">{numberFormatter.format(workers?.totals.reserved || 0)}</p>
        </div>
        <div className="rounded-xl bg-slate-100 p-4 dark:bg-slate-700/40">
          <p className="text-xs uppercase tracking-wide text-slate-700 dark:text-slate-200">Scheduled</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">{numberFormatter.format(workers?.totals.scheduled || 0)}</p>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {workers?.workers.map((worker) => (
          <div key={worker.name} className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900/40">
            <div>
              <p className="font-medium text-gray-900 dark:text-white">{worker.name}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">{worker.online ? 'online' : 'offline'}</p>
            </div>
            <div className="flex gap-3 font-mono text-xs text-gray-600 dark:text-gray-300">
              <span>A {worker.active_count}</span>
              <span>R {worker.reserved_count}</span>
              <span>S {worker.scheduled_count}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 space-y-3 max-h-[56rem] overflow-y-auto pr-1">
        {jobs.length > 0 ? (
          jobs.map((job) => {
            const progressPercent = formatProgressPercent(job)
            const { statusCounts, geocodeCounts } = getJobCounts(job)
            return (
              <div key={job.task_id} className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-gray-900 dark:text-white">{job.label || job.kind}</p>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${jobStatusClasses[job.status] || jobStatusClasses.queued}`}>
                        {job.status}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                        {job.kind}
                      </span>
                    </div>
                    <p className="mt-2 text-xs font-mono text-gray-500 dark:text-gray-400">{job.task_id}</p>
                    {job.message && <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{job.message}</p>}
                  </div>
                  <div className="text-right text-sm text-gray-500 dark:text-gray-400">
                    <p>{formatAge(job.created_at)}</p>
                    <p>{job.finished_at ? formatTimestamp(job.finished_at) : job.started_at ? `Started ${formatAge(job.started_at)}` : 'Queued'}</p>
                  </div>
                </div>

                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                    <span>{numberFormatter.format(job.processed_items)} / {numberFormatter.format(job.total_items || job.processed_items)}</span>
                    <span>{progressPercent}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700">
                    <div className="h-2 rounded-full bg-blue-600 transition-all duration-300" style={{ width: `${progressPercent}%` }} />
                  </div>
                </div>

                {(Object.keys(statusCounts).length > 0 || Object.keys(geocodeCounts).length > 0) && (
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Probe Status</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(statusCounts).map(([statusName, count]) => (
                          <span key={statusName} className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                            {statusName}: {count}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Geocode Status</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(geocodeCounts).map(([statusName, count]) => (
                          <span key={statusName} className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                            {statusName}: {count}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {job.error && <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{job.error}</p>}
              </div>
            )
          })
        ) : (
          <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
            No Celery jobs recorded yet.
          </div>
        )}
      </div>
    </div>
  )
}
