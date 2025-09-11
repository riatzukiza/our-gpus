import { useState } from 'react'
import { useQuery, useQueryClient } from 'react-query'
import { Search, Download, RefreshCw, Cpu, Wifi, WifiOff, Trash2 } from 'lucide-react'
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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [clearing, setClearing] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probeMessage, setProbeMessage] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading, refetch } = useQuery(
    ['hosts', page, pageSize, filters, search],
    async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        size: pageSize.toString(),
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
      setProbeMessage(`${response.data.message}. Refreshing in 5 seconds...`)
      
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
      case 'offline': return 'text-red-500'
      case 'error': return 'text-orange-500'
      default: return 'text-gray-500'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'online': return <Wifi className="w-4 h-4" />
      case 'offline': return <WifiOff className="w-4 h-4" />
      default: return <Wifi className="w-4 h-4" />
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
        <div className="flex items-center space-x-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
            <input
              type="text"
              placeholder="Search by model, IP, or location..."
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          
          <select
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">All Status</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
            <option value="error">Error</option>
          </select>
          
          <select
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={filters.gpu === null ? '' : filters.gpu.toString()}
            onChange={(e) => setFilters({ ...filters, gpu: e.target.value === '' ? null : e.target.value === 'true' })}
          >
            <option value="">All Systems</option>
            <option value="true">GPU Enabled</option>
            <option value="false">CPU Only</option>
          </select>
          
          <select
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
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
          
          <button
            onClick={() => handleProbe()}
            disabled={probing}
            className={`px-4 py-2 ${probing ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'} text-white rounded-lg transition-colors flex items-center`}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${probing ? 'animate-spin' : ''}`} />
            {probing ? 'Probing...' : 'Probe All'}
          </button>
          
          <button
            onClick={() => handleExport('csv')}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center text-gray-700 dark:text-gray-300"
          >
            <Download className="w-4 h-4 mr-2" />
            Export
          </button>
          
          <button
            onClick={handleClearHosts}
            disabled={clearing}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            {clearing ? 'Clearing...' : 'Clear All'}
          </button>
        </div>
      </div>
      
      {probeMessage && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 px-4 py-3 rounded-lg">
          {probeMessage}
        </div>
      )}
      
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-700">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Host
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Version
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Latency
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Models
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                System
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Last Seen
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {hosts?.map((host) => (
              <tr key={host.id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                <td className="px-6 py-4 whitespace-nowrap">
                  <Link to={`/host/${host.id}`} className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">
                    {host.ip}:{host.port}
                  </Link>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={`inline-flex items-center ${getStatusColor(host.status)}`}>
                    {getStatusIcon(host.status)}
                    <span className="ml-2 capitalize">{host.status}</span>
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  {host.api_version || '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  {host.latency_ms ? `${Math.round(host.latency_ms)}ms` : '-'}
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-wrap gap-1">
                    {host.models.slice(0, 3).map((model, idx) => (
                      <span key={idx} className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                        {model}
                      </span>
                    ))}
                    {host.models.length > 3 && (
                      <span className="px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded">
                        +{host.models.length - 3}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  {host.gpu === 'available' || host.gpu_vram_mb ? (
                    <span className="inline-flex items-center">
                      <Cpu className="w-4 h-4 mr-1 text-green-500" />
                      {host.gpu_vram_mb ? 
                        `GPU ${(host.gpu_vram_mb / 1024).toFixed(1)}GB` : 
                        'GPU Available'
                      }
                    </span>
                  ) : (
                    <span className="inline-flex items-center">
                      <Cpu className="w-4 h-4 mr-1 text-gray-400" />
                      CPU Only
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  {format(new Date(host.last_seen), 'MMM d, HH:mm')}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => handleProbe(host.id)}
                      className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300"
                      title="Probe host"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteHost(host.id)}
                      className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
                      title="Delete host"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        
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
                      key={pageNum}
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
                          key={pageNum}
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