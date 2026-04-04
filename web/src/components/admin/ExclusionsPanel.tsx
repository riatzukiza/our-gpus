import { useQuery } from 'react-query'
import axios from 'axios'
import { RefreshCw } from 'lucide-react'

interface ExcludesResponse {
  static_excludes: string[]
  dynamic_excludes: string[]
  effective_count: number
  last_refreshed_at: string | null
}

export default function ExclusionsPanel() {
  const { data, isLoading, isFetching, refetch } = useQuery(
    ['admin-excludes'],
    async () => {
      const res = await axios.get('/api/admin/excludes')
      return res.data as ExcludesResponse
    },
    {
      refetchOnWindowFocus: false,
    }
  )

  const handleRefresh = async () => {
    await axios.post('/api/admin/excludes/dynamic/refresh')
    await refetch()
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-[#111]">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Constitutional Exclusions
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            CIDRs and networks the system will never touch. No workflow runs if this set is empty.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isFetching}
          className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800 disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh dynamic
        </button>
      </div>

      {isLoading ? (
        <div className="mt-4 text-sm text-gray-500 dark:text-gray-400">
          Loading exclusions…
        </div>
      ) : (
        <div className="mt-5 grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          {/* Exclusion Lists */}
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-gray-500 dark:text-gray-400 mb-2">
                Static Exclusions ({data?.static_excludes?.length ?? 0})
              </div>
              <div className="max-h-32 overflow-y-auto font-mono text-[11px] bg-gray-50 dark:bg-gray-900/40 rounded-lg p-3 space-y-0.5">
                {data?.static_excludes?.slice(0, 20).map((cidr) => (
                  <div key={cidr} className="text-gray-700 dark:text-gray-200">
                    {cidr}
                  </div>
                ))}
                {(data?.static_excludes?.length ?? 0) > 20 && (
                  <div className="text-gray-400 text-[10px]">
                    +{data!.static_excludes.length - 20} more
                  </div>
                )}
              </div>
            </div>

            {data?.dynamic_excludes && data.dynamic_excludes.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold text-gray-500 dark:text-gray-400 mb-2">
                  Dynamic Exclusions ({data.dynamic_excludes.length})
                </div>
                <div className="max-h-24 overflow-y-auto font-mono text-[11px] bg-gray-50 dark:bg-gray-900/40 rounded-lg p-3 space-y-0.5">
                  {data.dynamic_excludes.slice(0, 15).map((cidr, idx) => (
                    <div key={idx} className="text-gray-600 dark:text-gray-300">
                      {cidr}
                    </div>
                  ))}
                  {data.dynamic_excludes.length > 15 && (
                    <div className="text-gray-400 text-[10px]">
                      +{data.dynamic_excludes.length - 15} more
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Stats */}
          <div className="space-y-3 text-xs text-gray-500 dark:text-gray-400">
            <div className="rounded-lg border border-gray-200 dark:border-gray-800 p-4">
              <div className="text-gray-400 dark:text-gray-500">Effective CIDRs</div>
              <div className="mt-1 text-2xl font-mono font-medium text-gray-900 dark:text-white">
                {data?.effective_count?.toLocaleString() ?? 0}
              </div>
            </div>

            {data?.last_refreshed_at && (
              <div className="text-gray-500 dark:text-gray-400">
                <span className="text-gray-400 dark:text-gray-500">Dynamic refreshed: </span>
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {data.last_refreshed_at}
                </span>
              </div>
            )}

            <div className="rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-3 text-amber-800 dark:text-amber-200">
              <p className="font-medium">Constitutional Layer</p>
              <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">
                These exclusions apply to all discovery strategies. They cannot be bypassed by workflows.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}