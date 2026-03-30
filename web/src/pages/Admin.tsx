import { useState } from 'react'
import { useQuery } from 'react-query'
import axios from 'axios'
import { format, formatDistanceToNowStrict } from 'date-fns'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Clock3,
  Database,
  Globe,
  Key,
  Loader,
  Play,
  Radar,
  RefreshCw,
  Square,
  ShieldAlert,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import ScannerWorldMap, { type HostPoint } from '../components/ScannerWorldMap'
import type { CountryCount } from '../lib/countryLookup'
import {
  clearStoredAdminApiKey,
  getStoredAdminApiKey,
  setStoredAdminApiKey,
} from '../lib/adminAuth'

type DashboardStatus = 'running' | 'stopping' | 'stopped' | 'not_running'

interface SchedulerStats {
  total_blocks: number
  scanned_blocks: number
  unscanned_blocks: number
  total_yield: number
  avg_pheromone: number
}

interface CurrentJob {
  cidr: string
  scan_uuid: string
  started_at: string
  output_file: string
  log_file: string
  port: string
  rate: number
  estimated_duration_s: number
}

interface RecentResult {
  cidr: string
  scan_uuid: string
  started_at: string
  completed_at: string
  output_file: string
  log_file: string
  hosts_found: number
  duration_ms: number
  success: boolean
  error: string | null
}

interface TopBlock {
  cidr: string
  pheromone: number
  scan_count: number
  cumulative_yield: number
  last_scan: string | null
}

interface SchedulerSnapshot {
  status: DashboardStatus
  started_at: string | null
  uptime_seconds: number | null
  prefix_len: number | null
  estimated_block_duration_s: number | null
  config: {
    port: string
    rate: number
    max_block_duration_s: number
    min_scan_interval_s: number
  } | null
  stats: SchedulerStats
  current_job: CurrentJob | null
  recent_results: RecentResult[]
  top_blocks: TopBlock[]
  last_error: string | null
}

interface HistoryEntry {
  scan_id: number
  cidr: string | null
  status: string
  started_at: string | null
  completed_at: string | null
  hosts_found: number
  failed_rows: number
  processed_rows: number
  error_message: string | null
}

interface GeographySummary {
  known_hosts: number
  unknown_hosts: number
  countries: CountryCount[]
  points?: HostPoint[]
}

interface DashboardResponse {
  status: DashboardStatus
  scheduler: SchedulerSnapshot
  history: HistoryEntry[]
  geography: GeographySummary
}

interface CurrentLogsResponse {
  status: 'running' | 'idle' | 'not_running'
  scan?: {
    cidr: string
    scan_uuid: string
    started_at: string
    port: string
    rate: number
    estimated_duration_s: number
  }
  log_file?: string
  lines?: number
  logs?: string
  message?: string
  last_error?: string | null
}

interface ProbeStatsResponse {
  total_hosts: number
  probes_completed: number
  success_count: number
  error_count: number
  timeout_count: number
  host_status_breakdown: Record<string, number>
  sample_errors: string[]
}

interface WorkerInfo {
  name: string
  online: boolean
  active_count: number
  reserved_count: number
  scheduled_count: number
}

interface CeleryJob {
  task_id: string
  kind: string
  label: string | null
  status: string
  celery_state: string
  total_items: number
  processed_items: number
  success_items: number
  failed_items: number
  message: string | null
  error: string | null
  payload: Record<string, unknown>
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

interface AdminJobsResponse {
  workers: {
    workers: WorkerInfo[]
    totals: {
      workers: number
      active: number
      reserved: number
      scheduled: number
    }
  }
  summary: Record<string, Record<string, number>>
  jobs: CeleryJob[]
}

const numberFormatter = new Intl.NumberFormat()

const statusClasses: Record<DashboardStatus, string> = {
  running: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200',
  stopping: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200',
  stopped: 'bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200',
  not_running: 'bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200',
}

const resultClasses = (success: boolean) =>
  success
    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
    : 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200'

const formatTimestamp = (value: string | null) =>
  value ? format(new Date(value), 'MMM d, yyyy HH:mm:ss') : 'Never'

const formatAge = (value: string | null) =>
  value ? formatDistanceToNowStrict(new Date(value), { addSuffix: true }) : 'Never'

const formatDurationMs = (value: number) =>
  value >= 60_000 ? `${(value / 60_000).toFixed(1)}m` : `${Math.max(1, Math.round(value / 1000))}s`

const formatSeconds = (value: number | null) => {
  if (value == null) {
    return 'n/a'
  }

  if (value >= 3600) {
    return `${(value / 3600).toFixed(1)}h`
  }

  if (value >= 60) {
    return `${(value / 60).toFixed(1)}m`
  }

  return `${Math.round(value)}s`
}

const jobStatusClasses: Record<string, string> = {
  queued: 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-200',
  started: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200',
  success: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200',
  failure: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200',
}

const formatProgressPercent = (job: CeleryJob) => {
  if (job.total_items <= 0) {
    return job.status === 'success' ? 100 : 0
  }

  return Math.min(100, Math.round((job.processed_items / job.total_items) * 100))
}

const getJobCounts = (job: CeleryJob) => {
  const payload = job.payload || {}
  const statusCounts = (payload.status_counts as Record<string, number> | undefined) || {}
  const geocodeCounts = (payload.geocode_counts as Record<string, number> | undefined) || {}
  return { statusCounts, geocodeCounts }
}

const getErrorMessage = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail || error.response?.data?.message || error.message
  }

  return error instanceof Error ? error.message : 'Unknown error'
}

export default function Admin() {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [activeAction, setActiveAction] = useState<'start' | 'stop' | null>(null)
  const [queueAction, setQueueAction] = useState<'probe' | 'geocode' | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [apiKeyDraft, setApiKeyDraft] = useState(() => getStoredAdminApiKey())
  const [adminKey, setAdminKey] = useState(() => getStoredAdminApiKey())
  const [probeLimit, setProbeLimit] = useState('1000')
  const [probeBatchSize, setProbeBatchSize] = useState('100')
  const [geocodeLimit, setGeocodeLimit] = useState('1000')
  const [geocodeBatchSize, setGeocodeBatchSize] = useState('100')

  const {
    data: sessionData,
    isLoading: sessionLoading,
    isError: sessionError,
    error: sessionErrorValue,
    refetch: refetchSession,
  } = useQuery(
    ['admin-session', adminKey],
    async () => {
      const response = await axios.get('/api/admin/session')
      return response.data as { authorized: boolean }
    },
    {
      enabled: Boolean(adminKey),
      retry: false,
      refetchOnWindowFocus: false,
    }
  )

  const isAuthorized = Boolean(adminKey) && !sessionError && sessionData?.authorized === true

  const { data, isLoading, isFetching, refetch } = useQuery(
    ['aco-dashboard'],
    async () => {
      const response = await axios.get('/api/aco/dashboard')
      return response.data as DashboardResponse
    },
    {
      enabled: isAuthorized,
      refetchInterval: 5000,
      refetchIntervalInBackground: true,
    }
  )

  const { data: jobsData, isFetching: jobsFetching, refetch: refetchJobs } = useQuery(
    ['admin-jobs'],
    async () => {
      const response = await axios.get('/api/admin/jobs?limit=80')
      return response.data as AdminJobsResponse
    },
    {
      enabled: isAuthorized,
      refetchInterval: 3000,
      refetchIntervalInBackground: true,
    }
  )

  const { data: probeStats, isFetching: probeStatsFetching, refetch: refetchProbeStats } = useQuery(
    ['probe-stats'],
    async () => {
      const response = await axios.get('/api/probe-stats?minutes=5')
      return response.data as ProbeStatsResponse
    },
    {
      enabled: isAuthorized,
      refetchInterval: 5000,
      refetchIntervalInBackground: true,
    }
  )

  const { data: logData, isFetching: logsFetching, refetch: refetchLogs } = useQuery(
    ['aco-current-logs'],
    async () => {
      const response = await axios.get('/api/aco/logs/current?lines=300')
      return response.data as CurrentLogsResponse
    },
    {
      enabled: isAuthorized && showLogs,
      refetchInterval: showLogs ? 2000 : false,
      refetchIntervalInBackground: showLogs,
    }
  )

  const scheduler = data?.scheduler
  const geography = data?.geography
  const history = data?.history || []
  const status = scheduler?.status || 'not_running'
  const currentJob = scheduler?.current_job
  const recentResults = scheduler?.recent_results || []
  const topBlocks = scheduler?.top_blocks || []
  const celeryWorkers = jobsData?.workers
  const celeryJobs = jobsData?.jobs || []

  const handleUnlock = async () => {
    const nextKey = apiKeyDraft.trim()
    if (!nextKey) {
      setMessage({ type: 'error', text: 'Enter an admin API key to unlock the control room.' })
      return
    }

    setStoredAdminApiKey(nextKey)
    setAdminKey(nextKey)
    setMessage(null)
    const result = await refetchSession()
    if (result.error) {
      setMessage({ type: 'error', text: `Unlock failed: ${getErrorMessage(result.error)}` })
    }
  }

  const handleLock = () => {
    clearStoredAdminApiKey()
    setAdminKey('')
    setApiKeyDraft('')
    setMessage(null)
  }

  const queueBacklogAction = async (kind: 'probe' | 'geocode') => {
    setQueueAction(kind)
    setMessage(null)

    try {
      if (kind === 'probe') {
        const response = await axios.post(
          `/api/probe/discovered?limit=${probeLimit.trim() || '1000'}&batch_size=${probeBatchSize.trim() || '100'}`
        )
        setMessage({ type: 'success', text: response.data.message || 'Queued discovered probe backlog.' })
      } else {
        const response = await axios.post(
          `/api/geocode/backlog?limit=${geocodeLimit.trim() || '1000'}&batch_size=${geocodeBatchSize.trim() || '100'}`
        )
        setMessage({ type: 'success', text: response.data.message || 'Queued geocode backlog.' })
      }

      await Promise.all([refetchJobs(), refetchProbeStats()])
    } catch (error) {
      setMessage({ type: 'error', text: `${kind === 'probe' ? 'Probe' : 'Geocode'} queue failed: ${getErrorMessage(error)}` })
    } finally {
      setQueueAction(null)
    }
  }

  if (!adminKey || sessionLoading || (!isAuthorized && sessionError)) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-12">
        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-start gap-4">
            <div className="rounded-xl bg-blue-50 p-3 text-blue-600 dark:bg-blue-900/30 dark:text-blue-200">
              {isAuthorized ? <ShieldCheck className="h-6 w-6" /> : <ShieldAlert className="h-6 w-6" />}
            </div>
            <div className="flex-1">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Admin Control Room</h2>
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                Enter the shared admin API key. This is the same federation token you already use with proxx.
              </p>
            </div>
          </div>

          {message && (
            <div
              className={`mt-6 flex items-center gap-3 rounded-xl p-4 text-sm ${
                message.type === 'success'
                  ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200'
                  : 'bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-200'
              }`}
            >
              {message.type === 'success' ? <CheckCircle className="h-5 w-5" /> : <AlertCircle className="h-5 w-5" />}
              <span>{message.text}</span>
            </div>
          )}

          {sessionError && !isAuthorized && (
            <div className="mt-6 rounded-xl bg-rose-50 p-4 text-sm text-rose-800 dark:bg-rose-900/20 dark:text-rose-200">
              {getErrorMessage(sessionErrorValue)}
            </div>
          )}

          <div className="mt-6 space-y-4">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Shared Admin API Key
            </label>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="relative flex-1">
                <Key className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="password"
                  value={apiKeyDraft}
                  onChange={(event) => setApiKeyDraft(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white py-3 pl-10 pr-4 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  placeholder="Enter admin key"
                />
              </div>
              <button
                type="button"
                onClick={handleUnlock}
                className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700"
              >
                Unlock Admin
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const handleSchedulerAction = async (action: 'start' | 'stop') => {
    setActiveAction(action)
    setMessage(null)

    try {
      const response = await axios.post(`/api/aco/scan/${action}`)
      const nextStatus = response.data.status as string

      if (action === 'start') {
        setMessage({
          type: 'success',
          text:
            nextStatus === 'already_running'
              ? 'ACO scheduler is already active.'
              : 'ACO scheduler started successfully.',
        })
      } else {
        setMessage({
          type: 'success',
          text:
            nextStatus === 'stop_requested'
              ? 'Stop requested. The current block will finish before the scheduler goes idle.'
              : 'ACO scheduler stopped.',
        })
      }

      await refetch()
    } catch (error) {
      setMessage({
        type: 'error',
        text: `${action === 'start' ? 'Start' : 'Stop'} failed: ${getErrorMessage(error)}`,
      })
    } finally {
      setActiveAction(null)
    }
  }

  if (isLoading || !scheduler || !geography) {
    return (
      <div className="flex justify-center py-16">
        <Loader className="h-10 w-10 animate-spin text-blue-600" />
      </div>
    )
  }

  const overviewCards = [
    {
      label: 'Scheduler Status',
      value: status.replace('_', ' '),
      detail: currentJob ? currentJob.cidr : 'No block currently scanning',
      icon: Activity,
    },
    {
      label: 'Blocks Scanned',
      value: `${numberFormatter.format(scheduler.stats.scanned_blocks)} / ${numberFormatter.format(
        scheduler.stats.total_blocks
      )}`,
      detail: `${numberFormatter.format(scheduler.stats.unscanned_blocks)} still eligible`,
      icon: Radar,
    },
    {
      label: 'Hosts Found',
      value: numberFormatter.format(scheduler.stats.total_yield),
      detail: `${numberFormatter.format(history.length)} recent persisted ingests`,
      icon: Database,
    },
    {
      label: 'Geocoded Hosts',
      value: numberFormatter.format(geography.known_hosts),
      detail: `${numberFormatter.format(geography.unknown_hosts)} still missing geography`,
      icon: Globe,
    },
  ]

  return (
    <div className="space-y-6 px-4 py-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">ACO Scanner</h2>
          <p className="mt-2 max-w-3xl text-sm text-gray-500 dark:text-gray-400">
            Live control room for the bounded block scanner, including current jobs, recent block
            results, and where geocoded hosts are showing up globally.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
            <RefreshCw className={`h-4 w-4 ${(isFetching || jobsFetching || probeStatsFetching) ? 'animate-spin' : ''}`} />
            Polling admin state
          </div>
          <button
            type="button"
            onClick={handleLock}
            className="rounded-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Lock Admin
          </button>
        </div>
      </div>

      {message && (
        <div
          className={`flex items-center gap-3 rounded-xl p-4 text-sm ${
            message.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200'
              : 'bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-200'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle className="h-5 w-5" />
          ) : (
            <AlertCircle className="h-5 w-5" />
          )}
          <span>{message.text}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {overviewCards.map((card) => {
          const Icon = card.icon

          return (
            <div
              key={card.label}
              className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{card.label}</p>
                  <p className="mt-2 text-2xl font-semibold capitalize text-gray-900 dark:text-white">
                    {card.value}
                  </p>
                </div>
                <div className="rounded-lg bg-blue-50 p-2 text-blue-600 dark:bg-blue-900/20 dark:text-blue-300">
                  <Icon className="h-5 w-5" />
                </div>
              </div>
              <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">{card.detail}</p>
            </div>
          )
        })}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Operator Actions</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Queue background probing and geocoding here. Operator controls stay off the public explore page.
                </p>
              </div>
              <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-200">
                Admin only
              </span>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Probe Discovered Hosts</h4>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Queue Celery probe batches for newly discovered hosts that have not been validated yet.
                </p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <label className="text-sm text-gray-600 dark:text-gray-300">
                    <span className="mb-1 block">Limit</span>
                    <input
                      value={probeLimit}
                      onChange={(event) => setProbeLimit(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  </label>
                  <label className="text-sm text-gray-600 dark:text-gray-300">
                    <span className="mb-1 block">Batch Size</span>
                    <input
                      value={probeBatchSize}
                      onChange={(event) => setProbeBatchSize(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => queueBacklogAction('probe')}
                  disabled={queueAction !== null}
                  className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
                >
                  {queueAction === 'probe' ? <Loader className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
                  Queue Probe Backlog
                </button>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Geocode Missing Geography</h4>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Queue local GeoIP lookups for already-probed hosts still missing country or coordinates.
                </p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <label className="text-sm text-gray-600 dark:text-gray-300">
                    <span className="mb-1 block">Limit</span>
                    <input
                      value={geocodeLimit}
                      onChange={(event) => setGeocodeLimit(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  </label>
                  <label className="text-sm text-gray-600 dark:text-gray-300">
                    <span className="mb-1 block">Batch Size</span>
                    <input
                      value={geocodeBatchSize}
                      onChange={(event) => setGeocodeBatchSize(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => queueBacklogAction('geocode')}
                  disabled={queueAction !== null}
                  className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-slate-800 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-400"
                >
                  {queueAction === 'geocode' ? <Loader className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
                  Queue Geocode Backlog
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Probe Snapshot</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Recent probe outcomes from the last five minutes and current host status distribution.
                </p>
              </div>
              <button
                type="button"
                onClick={() => refetchProbeStats()}
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
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Celery Jobs</h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Live queue visibility for probe, geocode, ingest, and backlog tasks.
              </p>
            </div>
            <button
              type="button"
              onClick={() => refetchJobs()}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Refresh
            </button>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-4">
            <div className="rounded-xl bg-gray-50 p-4 dark:bg-gray-900/40">
              <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Workers</p>
              <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">{numberFormatter.format(celeryWorkers?.totals.workers || 0)}</p>
            </div>
            <div className="rounded-xl bg-blue-50 p-4 dark:bg-blue-900/20">
              <p className="text-xs uppercase tracking-wide text-blue-700 dark:text-blue-200">Active</p>
              <p className="mt-2 text-2xl font-semibold text-blue-900 dark:text-blue-100">{numberFormatter.format(celeryWorkers?.totals.active || 0)}</p>
            </div>
            <div className="rounded-xl bg-amber-50 p-4 dark:bg-amber-900/20">
              <p className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-200">Reserved</p>
              <p className="mt-2 text-2xl font-semibold text-amber-900 dark:text-amber-100">{numberFormatter.format(celeryWorkers?.totals.reserved || 0)}</p>
            </div>
            <div className="rounded-xl bg-slate-100 p-4 dark:bg-slate-700/40">
              <p className="text-xs uppercase tracking-wide text-slate-700 dark:text-slate-200">Scheduled</p>
              <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">{numberFormatter.format(celeryWorkers?.totals.scheduled || 0)}</p>
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {celeryWorkers?.workers.map((worker) => (
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

          <div className="mt-6 space-y-3 max-h-[44rem] overflow-y-auto pr-1">
            {celeryJobs.length > 0 ? (
              celeryJobs.map((job) => {
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
                        {job.message && (
                          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{job.message}</p>
                        )}
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

                    {job.error && (
                      <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{job.error}</p>
                    )}
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
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Scheduler Control
                </h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Start or stop the background scanner without dropping the dashboard.
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium uppercase tracking-wide ${statusClasses[status]}`}
              >
                {status.replace('_', ' ')}
              </span>
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => handleSchedulerAction('start')}
                disabled={activeAction !== null || status === 'running' || status === 'stopping'}
                className="flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
              >
                {activeAction === 'start' ? (
                  <Loader className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Start Scheduler
              </button>
              <button
                type="button"
                onClick={() => handleSchedulerAction('stop')}
                disabled={activeAction !== null || status === 'stopped' || status === 'not_running'}
                className="flex items-center justify-center gap-2 rounded-lg bg-slate-800 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {activeAction === 'stop' ? (
                  <Loader className="h-4 w-4 animate-spin" />
                ) : (
                  <Square className="h-4 w-4" />
                )}
                Stop Scheduler
              </button>
            </div>

            <dl className="mt-5 space-y-3 text-sm text-gray-600 dark:text-gray-300">
              <div className="flex items-center justify-between gap-3">
                <dt>Port</dt>
                <dd className="font-mono">{scheduler.config?.port || '11434'}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt>Rate</dt>
                <dd className="font-mono">
                  {numberFormatter.format(scheduler.config?.rate || 100000)} pps
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt>Block Size</dt>
                <dd className="font-mono">/{scheduler.prefix_len ?? 'n/a'}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt>Target Duration</dt>
                <dd className="font-mono">
                  {formatSeconds(scheduler.estimated_block_duration_s)} / {formatSeconds(
                    scheduler.config?.max_block_duration_s || null
                  )}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt>Cooldown Between Revisits</dt>
                <dd className="font-mono">
                  {formatSeconds(scheduler.config?.min_scan_interval_s || null)}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt>Scheduler Uptime</dt>
                <dd className="font-mono">{formatSeconds(scheduler.uptime_seconds)}</dd>
              </div>
            </dl>

            {scheduler.last_error && (
              <div className="mt-5 rounded-lg bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-900/20 dark:text-rose-200">
                <p className="font-medium">Last scheduler error</p>
                <p className="mt-1 break-words">{scheduler.last_error}</p>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start gap-3">
              <Clock3 className="mt-1 h-5 w-5 text-blue-600 dark:text-blue-300" />
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Current Job</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  The block currently being scanned, if the scheduler is active.
                </p>
              </div>
            </div>

            {currentJob ? (
              <div className="mt-5 space-y-4">
                <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-900/20">
                  <p className="text-xs uppercase tracking-wide text-blue-700 dark:text-blue-200">
                    Active Block
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-blue-900 dark:text-blue-100">
                    {currentJob.cidr}
                  </p>
                  <p className="mt-2 text-sm text-blue-700 dark:text-blue-200">
                    Started {formatAge(currentJob.started_at)} and capped at about{' '}
                    {formatSeconds(currentJob.estimated_duration_s)}.
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

          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <Terminal className="h-5 w-5 text-gray-600 dark:text-gray-300" />
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Live Scanner Logs</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Real-time masscan output from the current block.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowLogs(!showLogs)}
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
                    Scheduler is not running. Start it to see live logs.
                  </div>
                ) : logData?.status === 'idle' ? (
                  <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-400">
                    {logData.message || 'No scan currently running.'}
                    {logData.last_error && (
                      <p className="mt-2 text-rose-600 dark:text-rose-400">Last error: {logData.last_error}</p>
                    )}
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
                        onClick={() => refetchLogs()}
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
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <ScannerWorldMap
            countries={geography.countries}
            knownHosts={geography.known_hosts}
            unknownHosts={geography.unknown_hosts}
            points={geography.points}
          />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800 xl:col-span-2">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Block Jobs</h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Live block-level results from the in-process scheduler.
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
              {numberFormatter.format(recentResults.length)} results
            </span>
          </div>

          <div className="mt-5 space-y-3">
            {recentResults.length > 0 ? (
              recentResults.map((result) => (
                <div
                  key={`${result.scan_uuid}-${result.completed_at}`}
                  className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-gray-900 dark:text-white">{result.cidr}</p>
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ${resultClasses(result.success)}`}
                        >
                          {result.success ? 'completed' : 'failed'}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                        Finished {formatAge(result.completed_at)} after {formatDurationMs(result.duration_ms)}.
                      </p>
                    </div>

                    <div className="text-right text-sm">
                      <p className="font-semibold text-gray-900 dark:text-white">
                        {numberFormatter.format(result.hosts_found)} hosts
                      </p>
                      <p className="text-gray-500 dark:text-gray-400">{result.scan_uuid}</p>
                    </div>
                  </div>

                  {result.error && (
                    <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{result.error}</p>
                  )}
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
                No live block results yet.
              </div>
            )}
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
                <div
                  key={block.cidr}
                  className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-mono text-sm font-medium text-gray-900 dark:text-white">
                      {block.cidr}
                    </p>
                    <p className="text-sm font-semibold text-blue-600 dark:text-blue-300">
                      {block.pheromone.toFixed(3)}
                    </p>
                  </div>
                  <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                    {numberFormatter.format(block.cumulative_yield)} hosts over{' '}
                    {numberFormatter.format(block.scan_count)} scans.
                  </p>
                  <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                    Last scan: {formatAge(block.last_scan)}
                  </p>
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

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Persisted ACO Ingest History</h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Blocks that were ingested into the database after masscan finished.
        </p>

        <div className="mt-5 space-y-3">
          {history.length > 0 ? (
            history.slice(0, 10).map((entry) => (
              <div
                key={entry.scan_id}
                className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-gray-900 dark:text-white">
                        {entry.cidr || `scan #${entry.scan_id}`}
                      </p>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                        {entry.status}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                      Started {formatAge(entry.started_at)} and recorded{' '}
                      {numberFormatter.format(entry.hosts_found)} hosts.
                    </p>
                  </div>

                  <div className="text-right text-sm text-gray-500 dark:text-gray-400">
                    <p>{formatTimestamp(entry.started_at)}</p>
                    <p>{entry.completed_at ? formatTimestamp(entry.completed_at) : 'Still processing'}</p>
                  </div>
                </div>

                {entry.error_message && (
                  <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">
                    {entry.error_message}
                  </p>
                )}
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
              No ACO block ingests have been recorded yet.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
