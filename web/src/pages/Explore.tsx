import { useState } from 'react'
import { useQuery, useQueryClient } from 'react-query'
import { Search, Download, RefreshCw, Cpu, Wifi, WifiOff, Trash2, ArrowUpDown, ArrowUp, ArrowDown, AlertCircle, Clock, HelpCircle } from 'lucide-react'
import axios from 'axios'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'

interface Host {
  id: number
  ip: string
  port: number
  status: string
  last_seen: string
  latency_ms: number | null
  api_version: string | null
  gpu: string | null
  gpu_vram_mb: number | null
  models: string[]
}

export default function Explore() {
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    model: '',
    family: '',
    gpu: null as boolean | null,
    status: ''
  })
  const [sortBy, setSortBy] = useState('last_seen')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [clearing, setClearing] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probeMessage, setProbeMessage] = useState('')
  const [probeStats, setProbeStats] = useState<any>(null)
  const queryClient = useQueryClient()

  // Fetch available model names for dropdown
  const { data: modelNamesData, isLoading: modelsLoading } = useQuery(
    ['model-names'],
    async () => {
      const response = await axios.get('/api/models/names')
      return response.data.models as string[]
    },
    {
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
      cacheTime: 10 * 60 * 1000, // 10 minutes
    }
  )

  // Use empty array as fallback if data is not available
  const modelNames = modelNamesData || []

  // Fetch available model families for family filter
  const { data: modelFamiliesData } = useQuery(
    ['model-families'],
    async () => {
      const response = await axios.get('/api/models/families')
      return response.data.families as string[]
    },
    {
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
      cacheTime: 10 * 60 * 1000, // 10 minutes
    }
  )

  // Use empty array as fallback if data is not available
  const modelFamilies = modelFamiliesData || []

  const startProbePolling = () => {
    const pollInterval = setInterval(async () => {
      try {
        const statsResponse = await axios.get(`/api/probe-stats?minutes=2`)
        const stats = statsResponse.data
        setProbeStats(stats)
        
        // Update message with progress
        const progress = `Probed: ${stats.probes_completed}/${stats.total_hosts} - Success: ${stats.success_count}, Errors: ${stats.error_count}, Timeouts: ${stats.timeout_count}`
        setProbeMessage(`Probing in progress... ${progress}`)
        
        // Check if we should stop polling (no new probes in last minute suggests completion)
        if (stats.probes_completed > 0 && stats.probes_completed >= stats.total_hosts * 0.95) {
          clearInterval(pollInterval)
          setProbeMessage(`Probe batch completed! Success: ${stats.success_count}, Errors: ${stats.error_count}, Timeouts: ${stats.timeout_count}. Refreshing data...`)
          setTimeout(() => {
            refetch()
            setProbing(false)
            setProbeMessage('')
            setProbeStats(null)
          }, 2000)
        }
      } catch (error) {
        console.error('Error polling probe status:', error)
        clearInterval(pollInterval)
        setProbeMessage('Error monitoring probe progress. Check logs.')
        setProbing(false)
      }
    }, 3000) // Poll every 3 seconds
  }

  const { data, isLoading, refetch } = useQuery(
    ['hosts', page, pageSize, filters, search, sortBy],
    async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        size: pageSize.toString(),
        sort: sortBy,
        ...(filters.model && { model: filters.model }),
        ...(filters.family && { family: filters.family }),
        ...(filters.gpu !== null && { gpu: filters.gpu.toString() }),
        ...(filters.status && { status: filters.status })
      })
      
      const response = await axios.get(`/api/hosts?${params}`)
      return response.data as {
        items: Host[]
        total: number
        page: number
        size: number
        pages: number
      }
    },
    {
      keepPreviousData: true
    }
  )
  
  const hosts = data?.items || []
  const totalHosts = data?.total || 0
  const totalPages = data?.pages || 0

  const handleClearHosts = async () => {
    if (!window.confirm('Are you sure you want to clear all hosts? This action cannot be undone.')) {
      return
    }
    
    setClearing(true)
    try {
      await axios.delete('/api/hosts')
      queryClient.invalidateQueries(['hosts'])
      alert('All hosts have been cleared successfully')
    } catch (error) {
      console.error('Failed to clear hosts:', error)
      alert('Failed to clear hosts. Please try again.')
    } finally {
      setClearing(false)
    }
  }

  const handleDeleteHost = async (hostId: number) => {
    if (!window.confirm('Are you sure you want to delete this host?')) {
      return
    }
    
    try {
      await axios.delete(`/api/hosts/${hostId}`)
      queryClient.invalidateQueries(['hosts'])
    } catch (error) {
      console.error('Failed to delete host:', error)
      alert('Failed to delete host. Please try again.')
    }
  }

  const handleExport = async (format: 'csv' | 'json') => {
    const params = new URLSearchParams({
      format,
      ...(filters.model && { model: filters.model }),
      ...(filters.family && { family: filters.family }),
      ...(filters.gpu !== null && { gpu: filters.gpu.toString() })
    })
    
    window.open(`/api/export?${params}`, '_blank')
  }

  const handleProbe = async (hostId?: number) => {
    // Safety check for large batches
    if (!hostId && totalHosts > 1000) {
      const confirmed = window.confirm(
        `You are about to probe ${totalHosts} hosts. This may take several minutes and use significant system resources. Continue?`
      )
      if (!confirmed) return
    }
    
    const payload: any = {}
    
    if (hostId) {
      payload.host_ids = [hostId]
    } else {
      // Only add filters if they have actual values
      const activeFilters: any = {}
      if (filters.model) activeFilters.model = filters.model
      if (filters.family) activeFilters.family = filters.family
      if (filters.status) activeFilters.status = filters.status
      if (filters.gpu !== null) activeFilters.gpu = filters.gpu
      
      if (Object.keys(activeFilters).length > 0) {
        payload.filter = activeFilters
      } else {
        // When no filters are set, explicitly request to probe all hosts
        payload.probe_all = true
      }
    }
    
    console.log('Probe payload:', payload)
    
    setProbing(true)
    setProbeMessage('')
    
    try {
      const response = await axios.post('/api/probe', payload, {
        headers: {
          'Content-Type': 'application/json'
        }
      })
      console.log('Probe response:', response.data)
      const baseMessage = response.data.message || `Queued probe tasks`
      
      // Start polling for probe progress using time-based approach
      startProbePolling()
      
      if (!hostId) {
        // Add context about total hosts when probing all/filtered
        const contextMessage = payload.probe_all 
          ? `(${totalHosts} total hosts)`
          : Object.keys(payload.filter || {}).length > 0 
            ? `(${totalHosts} matching hosts)`
            : `(limited to 100 hosts)`
        setProbeMessage(`${baseMessage} ${contextMessage}. Monitoring progress...`)
      } else {
        setProbeMessage(`${baseMessage}. Refreshing in 5 seconds...`)
        // For single host probes, use the old refresh logic
        setTimeout(() => {
          refetch()
          setProbing(false)
          setProbeMessage('')
        }, 5000)
      }
      
      // Refresh data after a delay to see probe results
      setTimeout(() => {
        refetch()
        setProbing(false)
        setProbeMessage('')
      }, 5000)
    } catch (error: any) {
      console.error('Probe error:', error)
      if (error.response) {
        console.error('Error response data:', error.response.data)
        console.error('Error response status:', error.response.status)
        console.error('Error response detail:', error.response.data?.detail)
      }
      setProbing(false)
      setProbeMessage('Failed to initiate probe')
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online': return 'text-green-500'
      case 'timeout': return 'text-yellow-500'
      case 'error': return 'text-red-500'
      case 'non_ollama': return 'text-blue-500'
      case 'unknown': return 'text-gray-500'
      default: return 'text-gray-500'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'online': return <Wifi className="w-4 h-4" />
      case 'timeout': return <Clock className="w-4 h-4" />
      case 'error': return <AlertCircle className="w-4 h-4" />
      case 'non_ollama': return <WifiOff className="w-4 h-4" />
      case 'unknown': return <HelpCircle className="w-4 h-4" />
      default: return <HelpCircle className="w-4 h-4" />
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
          Discovered Hosts
          {totalHosts > 0 && (
            <span className="ml-3 text-lg font-normal text-gray-600 dark:text-gray-400">
              {totalHosts} total {totalHosts === 1 ? 'host' : 'hosts'}
            </span>
          )}
        </h2>
      </div>
      
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow mb-6 p-4">
        {/* Search and basic filters row */}
        <div className="flex items-center space-x-4 mb-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
            <input
              type="text"
              placeholder="Search by model, IP, or location..."
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          
          <select
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">All Status</option>
            <option value="online">Online</option>
            <option value="timeout">Timeout</option>
            <option value="error">Error</option>
            <option value="non_ollama">Non-Ollama</option>
            <option value="unknown">Unknown</option>
          </select>
          
          <select
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.gpu === null ? '' : filters.gpu.toString()}
            onChange={(e) => setFilters({ ...filters, gpu: e.target.value === '' ? null : e.target.value === 'true' })}
          >
            <option value="">All Systems</option>
            <option value="true">GPU Enabled</option>
            <option value="false">CPU Only</option>
          </select>
          
          <select
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={pageSize.toString()}
            onChange={(e) => {
              setPageSize(parseInt(e.target.value))
              setPage(1) // Reset to first page when changing page size
            }}
          >
            <option value="10">10 per page</option>
            <option value="25">25 per page</option>
            <option value="50">50 per page</option>
            <option value="100">100 per page</option>
          </select>
          
          <select
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            title="Sort by"
          >
            <option value="last_seen">Sort: Last Seen</option>
            <option value="latency">Sort: Latency</option>
          </select>
          
          <button
            onClick={() => {
              setFilters({ model: '', family: '', gpu: null, status: '' })
              setSearch('')
              setSortBy('last_seen')
              setPage(1)
            }}
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors text-gray-700 dark:text-gray-300"
            title="Clear all filters"
          >
            Clear
          </button>
          
          <button
            onClick={() => handleProbe()}
            disabled={probing}
            className={`px-3 py-2 text-sm ${probing ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'} text-white rounded-lg transition-colors flex items-center`}
            title={`Probe ${totalHosts} hosts${Object.values(filters).some(v => v !== null && v !== '') ? ' (filtered)' : ' (all hosts)'}`}
          >
            <RefreshCw className={`w-3 h-3 mr-1.5 ${probing ? 'animate-spin' : ''}`} />
            {probing 
              ? 'Probing...' 
              : `Probe (${totalHosts})`
            }
          </button>
          
          <button
            onClick={() => handleExport('csv')}
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center text-gray-700 dark:text-gray-300"
          >
            <Download className="w-3 h-3 mr-1.5" />
            Export
          </button>
          
          <button
            onClick={handleClearHosts}
            disabled={clearing}
            className="px-3 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center"
          >
            <Trash2 className="w-3 h-3 mr-1.5" />
            {clearing ? 'Clearing...' : 'Clear All'}
          </button>
        </div>
        
        {/* Model filter row */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
              Model Family:
            </label>
            <select
              className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={filters.family}
              onChange={(e) => setFilters({ ...filters, family: e.target.value })}
              disabled={!modelFamilies.length}
            >
              <option value="">{!modelFamilies.length ? 'Loading families...' : 'All Families'}</option>
              {modelFamilies.length > 0 && modelFamilies.map((family: string) => (
                <option key={family} value={family}>
                  {family.charAt(0).toUpperCase() + family.slice(1)}
                </option>
              ))}
            </select>
          </div>
          
          <div className="flex items-center space-x-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
              Specific Model:
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-3 h-3" />
              <select
                className="pl-7 pr-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-48 max-w-80"
                value={filters.model}
                onChange={(e) => setFilters({ ...filters, model: e.target.value })}
                disabled={modelsLoading || !modelNames.length}
                title={filters.model || 'Select a model to filter'}
              >
                <option value="">{modelsLoading ? 'Loading models...' : !modelNames.length ? 'No models available' : `All Models (${modelNames.length})`}</option>
                {modelNames.length > 0 && modelNames.map((modelName: string) => (
                  <option key={modelName} value={modelName} title={modelName}>
                    {modelName.length > 40 ? modelName.substring(0, 40) + '...' : modelName}
                  </option>
              ))}
              </select>
            </div>
            {filters.model && (
              <button
                onClick={() => setFilters({ ...filters, model: '' })}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                title="Clear model filter"
              >
                ✕
              </button>
            )}
          </div>
          
          {(filters.model || filters.family) && (
            <div className="text-sm text-gray-600 dark:text-gray-400">
              {filters.family && (
                <span>Family: <span className="font-medium text-blue-600 dark:text-blue-400">{filters.family}</span></span>
              )}
              {filters.model && (
                <span>{filters.family && ' • '}Model: <span className="font-medium text-blue-600 dark:text-blue-400">{filters.model}</span></span>
              )}
            </div>
          )}
        </div>
      </div>
      
      {probeMessage && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 px-4 py-3 rounded-lg">
          <div className="flex items-center justify-between">
            <span>{probeMessage}</span>
            {probing && probeStats && (
              <div className="text-sm space-x-4">
                <span>✅ {probeStats.success_count}</span>
                <span>❌ {probeStats.error_count}</span>
                <span>⏱️ {probeStats.timeout_count}</span>
              </div>
            )}
          </div>
          {probing && probeStats && probeStats.progress_percent !== undefined && (
            <div className="mt-2">
              <div className="bg-blue-200 dark:bg-blue-800 rounded-full h-2">
                <div 
                  className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${probeStats.progress_percent}%` }}
                ></div>
              </div>
            </div>
          )}
        </div>
      )}
      
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
        <div className="min-w-[1200px]">
          <table className="w-full divide-y divide-gray-200 dark:divide-gray-700 table-fixed">
            <colgroup>
              <col className="w-36" />
              <col className="w-24" />
              <col className="w-20" />
              <col className="w-24" />
              <col className="w-80" />
              <col className="w-28" />
              <col className="w-24" />
              <col className="w-20" />
            </colgroup>
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  Host
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  Version
                </th>
                <th 
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 truncate"
                  onClick={() => setSortBy(sortBy === 'latency' ? 'last_seen' : 'latency')}
                >
                  <div className="flex items-center space-x-1">
                    <span>Latency</span>
                    {sortBy === 'latency' ? (
                      <ArrowUp className="w-3 h-3 flex-shrink-0" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 flex-shrink-0" />
                    )}
                  </div>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  Models
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  System
                </th>
                <th 
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 truncate"
                  onClick={() => setSortBy(sortBy === 'last_seen' ? 'latency' : 'last_seen')}
                >
                  <div className="flex items-center space-x-1">
                    <span className="truncate">Last Seen</span>
                    {sortBy === 'last_seen' ? (
                      <ArrowDown className="w-3 h-3 flex-shrink-0" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 flex-shrink-0" />
                    )}
                  </div>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
              {hosts?.map((host, index) => (
                <tr key={`host-${host.id}-${host.ip}-${index}`} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                  <td className="px-4 py-3 whitespace-nowrap truncate">
                    <Link to={`/host/${host.id}`} className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 text-sm">
                      {host.ip}:{host.port}
                    </Link>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap truncate">
                    <span className={`inline-flex items-center ${getStatusColor(host.status)}`}>
                      {getStatusIcon(host.status)}
                      <span className="ml-1 text-sm capitalize">{host.status === 'non_ollama' ? 'Non-Ollama' : host.status}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 truncate">
                    {host.api_version || '-'}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 truncate">
                    {host.latency_ms ? `${Math.round(host.latency_ms)}ms` : '-'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1 max-h-16 overflow-hidden">
                      {host.models.slice(0, 2).map((model, idx) => (
                        <span key={`${host.id}-model-${idx}`} className="px-2 py-1 text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded truncate max-w-32" title={model}>
                          {model.length > 15 ? model.substring(0, 12) + '...' : model}
                        </span>
                      ))}
                      {host.models.length > 2 && (
                        <span className="px-2 py-1 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded" title={`${host.models.length - 2} more models`}>
                          +{host.models.length - 2}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 truncate">
                    {host.gpu === 'available' || host.gpu_vram_mb ? (
                      <span className="inline-flex items-center">
                        <Cpu className="w-4 h-4 mr-1 text-green-500 flex-shrink-0" />
                        <span className="truncate">
                          {host.gpu_vram_mb ? 
                            `${(host.gpu_vram_mb / 1024).toFixed(1)}GB` : 
                            'GPU'
                          }
                        </span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center">
                        <Cpu className="w-4 h-4 mr-1 text-gray-400 flex-shrink-0" />
                        <span className="truncate">CPU</span>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 truncate">
                    {format(new Date(host.last_seen), 'MMM d, HH:mm')}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                    <div className="flex items-center space-x-1">
                      <button
                        onClick={() => handleProbe(host.id)}
                        className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 p-1 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors"
                        title="Probe host"
                      >
                        <RefreshCw className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleDeleteHost(host.id)}
                        className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 p-1 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                        title="Delete host"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        {isLoading && (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
        )}
        
        <div className="bg-gray-50 dark:bg-gray-800 px-4 py-3 flex items-center justify-between sm:px-6">
          <div className="flex-1 flex justify-between items-center sm:hidden">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-sm text-gray-700 dark:text-gray-300">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={page === totalPages || totalPages === 0}
              className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
          <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-gray-700 dark:text-gray-300">
                Showing{' '}
                <span className="font-medium">
                  {totalHosts > 0 ? ((page - 1) * pageSize + 1) : 0}
                </span>
                {' - '}
                <span className="font-medium">
                  {Math.min(page * pageSize, totalHosts)}
                </span>
                {' of '}
                <span className="font-medium">{totalHosts}</span>
                {' hosts'}
                {totalPages > 1 && (
                  <>
                    {' • Page '}
                    <span className="font-medium">{page}</span>
                    {' of '}
                    <span className="font-medium">{totalPages}</span>
                  </>
                )}
              </p>
            </div>
            <div>
              <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                {totalPages <= 7 ? (
                  // Show all pages if 7 or fewer
                  Array.from({ length: totalPages }, (_, i) => i + 1).map(pageNum => (
                    <button
                      key={`page-${pageNum}`}
                      onClick={() => setPage(pageNum)}
                      className={`relative inline-flex items-center px-4 py-2 border text-sm font-medium ${
                        pageNum === page
                          ? 'z-10 bg-blue-50 border-blue-500 text-blue-600 dark:bg-blue-900 dark:border-blue-400 dark:text-blue-300'
                          : 'border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
                      }`}
                    >
                      {pageNum}
                    </button>
                  ))
                ) : (
                  // Show page numbers with ellipsis for many pages
                  <>
                    {page > 2 && (
                      <>
                        <button
                          onClick={() => setPage(1)}
                          className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600"
                        >
                          1
                        </button>
                        {page > 3 && (
                          <span className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300">
                            ...
                          </span>
                        )}
                      </>
                    )}
                    
                    {Array.from(
                      { length: Math.min(3, totalPages) },
                      (_, i) => Math.max(1, Math.min(page - 1 + i, totalPages))
                    )
                      .filter((v, i, a) => a.indexOf(v) === i)
                      .map(pageNum => (
                        <button
                          key={`page-ellipsis-${pageNum}`}
                          onClick={() => setPage(pageNum)}
                          className={`relative inline-flex items-center px-4 py-2 border text-sm font-medium ${
                            pageNum === page
                              ? 'z-10 bg-blue-50 border-blue-500 text-blue-600 dark:bg-blue-900 dark:border-blue-400 dark:text-blue-300'
                              : 'border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
                          }`}
                        >
                          {pageNum}
                        </button>
                      ))}
                    
                    {page < totalPages - 1 && (
                      <>
                        {page < totalPages - 2 && (
                          <span className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300">
                            ...
                          </span>
                        )}
                        <button
                          onClick={() => setPage(totalPages)}
                          className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600"
                        >
                          {totalPages}
                        </button>
                      </>
                    )}
                  </>
                )}
                <button
                  onClick={() => setPage(p => Math.min(p + 1, totalPages))}
                  disabled={page === totalPages || totalPages === 0}
                  className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </nav>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}