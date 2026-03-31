import { useState } from 'react'
import { useQuery, useQueryClient } from 'react-query'
import { Search, Download, Cpu, Wifi, WifiOff, Trash2, ArrowUpDown, ArrowUp, ArrowDown, AlertCircle, Clock, HelpCircle } from 'lucide-react'
import axios from 'axios'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { getStoredAdminApiKey } from '../lib/adminAuth'

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
  geo_country?: string | null
  geo_city?: string | null
  groups?: string[] | null
  models: string[]
}

interface HostGroup {
  id: number
  name: string
  description: string | null
  country_filter: string | null
  system_filter: string | null
  host_count: number
}

export default function Explore() {
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    model: '',
    family: '',
    gpu: null as boolean | null,
    status: '',
    country: '',
    groupId: ''
  })
  const [sortBy, setSortBy] = useState('last_seen')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [clearing, setClearing] = useState(false)
  const queryClient = useQueryClient()
  const hasAdminKey = Boolean(getStoredAdminApiKey())

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

  const { data: countryData } = useQuery(
    ['host-countries'],
    async () => {
      const response = await axios.get('/api/hosts/countries')
      return response.data.countries as string[]
    },
    {
      retry: 1,
      staleTime: 5 * 60 * 1000,
    }
  )

  const countries = countryData || []

  const { data: groupsData } = useQuery(
    ['host-groups', hasAdminKey],
    async () => {
      const response = await axios.get('/api/admin/groups')
      return response.data as HostGroup[]
    },
    {
      enabled: hasAdminKey,
      retry: false,
      staleTime: 60 * 1000,
    }
  )

  const groups = groupsData || []

  const { data, isLoading } = useQuery(
    ['hosts', page, pageSize, filters, search, sortBy],
    async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        size: pageSize.toString(),
        sort: sortBy,
        ...(filters.model && { model: filters.model }),
        ...(filters.family && { family: filters.family }),
        ...(filters.gpu !== null && { gpu: filters.gpu.toString() }),
        ...(filters.status && { status: filters.status }),
        ...(filters.country && { country: filters.country }),
        ...(filters.groupId && { group_id: filters.groupId })
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
    // Build filter description for confirmation dialog
    const filterDescriptions = []
    if (filters.model) filterDescriptions.push(`model: "${filters.model}"`)
    if (filters.family) filterDescriptions.push(`family: "${filters.family}"`)
    if (filters.gpu !== null) filterDescriptions.push(`GPU: ${filters.gpu ? 'available' : 'unavailable'}`)
    if (filters.status) filterDescriptions.push(`status: "${filters.status}"`)
    if (filters.country) filterDescriptions.push(`country: "${filters.country}"`)
    if (filters.groupId) {
      const groupName = groups.find((group) => String(group.id) === filters.groupId)?.name || filters.groupId
      filterDescriptions.push(`group: "${groupName}"`)
    }
    if (search) filterDescriptions.push(`search: "${search}"`)
    
    const hasActiveFilters = filterDescriptions.length > 0
    const filterText = hasActiveFilters ? ` matching filters (${filterDescriptions.join(', ')})` : ''
    
    if (!window.confirm(`Are you sure you want to clear${hasActiveFilters ? ' filtered' : ' all'} hosts?${filterText ? `\n\nThis will only clear hosts${filterText}.` : ''}\n\nThis action cannot be undone.`)) {
      return
    }
    
    setClearing(true)
    try {
      // Use filtered endpoint if there are active filters, otherwise use the original endpoint
      if (hasActiveFilters) {
        // Build query parameters from current filters
        const params = new URLSearchParams()
        if (filters.model) params.append('model', filters.model)
        if (filters.family) params.append('family', filters.family)
        if (filters.gpu !== null) params.append('gpu', String(filters.gpu))
        if (filters.status) params.append('status', filters.status)
        if (filters.country) params.append('country', filters.country)
        if (filters.groupId) params.append('group_id', filters.groupId)
        
        console.log('Clearing hosts with filters:', { model: filters.model, family: filters.family, gpu: filters.gpu, status: filters.status, country: filters.country, groupId: filters.groupId })
        await axios.post('/api/hosts/clear-filtered', {
          model: filters.model || null,
          family: filters.family || null,
          gpu: filters.gpu,
          status: filters.status || null,
          country: filters.country || null,
          group_id: filters.groupId ? Number(filters.groupId) : null
        })
        alert(`Filtered hosts have been cleared successfully`)
      } else {
        await axios.delete('/api/hosts')
        alert('All hosts have been cleared successfully')
      }
      
      queryClient.invalidateQueries(['hosts'])
      // Reset to page 1 after clearing
      setPage(1)
    } catch (error) {
      console.error('Failed to clear hosts:', error)
      const axiosError = error as any
      if (axiosError.response) {
        console.error('Error response:', axiosError.response.data)
        console.error('Error status:', axiosError.response.status)
      }
      alert('Failed to clear hosts. Please try again.')
    } finally {
      setClearing(false)
    }
  }

  // Determine button text based on active filters
  const getClearButtonText = () => {
    if (clearing) return 'Clearing...'
    const hasActiveFilters = filters.model || filters.family || filters.gpu !== null || filters.status || filters.country || filters.groupId || search
    return hasActiveFilters ? 'Clear Filtered' : 'Clear All'
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
      ...(filters.gpu !== null && { gpu: filters.gpu.toString() }),
      ...(filters.country && { country: filters.country }),
      ...(filters.groupId && { group_id: filters.groupId })
    })
    
    window.open(`/api/export?${params}`, '_blank')
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
            value={filters.country}
            onChange={(e) => setFilters({ ...filters, country: e.target.value })}
          >
            <option value="">All Countries</option>
            {countries.map((country) => (
              <option key={country} value={country}>{country}</option>
            ))}
          </select>

          {hasAdminKey && (
            <select
              className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={filters.groupId}
              onChange={(e) => setFilters({ ...filters, groupId: e.target.value })}
            >
              <option value="">All Groups</option>
              {groups.map((group) => (
                <option key={group.id} value={String(group.id)}>{group.name}</option>
              ))}
            </select>
          )}
          
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
            type="button"
            onClick={() => {
              setFilters({ model: '', family: '', gpu: null, status: '', country: '', groupId: '' })
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
            onClick={() => handleExport('csv')}
            type="button"
            className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center text-gray-700 dark:text-gray-300"
          >
            <Download className="w-3 h-3 mr-1.5" />
            Export
          </button>
          
            {hasAdminKey && (
              <button
                onClick={handleClearHosts}
                type="button"
                disabled={clearing}
                className="px-3 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center"
                title={getClearButtonText()}
            >
              <Trash2 className="w-3 h-3 mr-1.5" />
              {getClearButtonText()}
            </button>
          )}
        </div>
        
        {/* Model filter row */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <label htmlFor="family-filter" className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
              Model Family:
            </label>
            <select
              id="family-filter"
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
            <label htmlFor="model-filter" className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
              Specific Model:
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-3 h-3" />
              <select
                id="model-filter"
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
                type="button"
                onClick={() => setFilters({ ...filters, model: '' })}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                title="Clear model filter"
              >
                ✕
              </button>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <label htmlFor="country-filter" className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
              Country:
            </label>
            <select
              id="country-filter"
              className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={filters.country}
              onChange={(e) => setFilters({ ...filters, country: e.target.value })}
            >
              <option value="">All Countries</option>
              {countries.map((country) => (
                <option key={country} value={country}>{country}</option>
              ))}
            </select>
            {filters.country && (
              <button
                type="button"
                onClick={() => setFilters({ ...filters, country: '' })}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                title="Clear country filter"
              >
                ✕
              </button>
            )}
          </div>

          {hasAdminKey && (
            <div className="flex items-center space-x-2">
              <label htmlFor="group-filter" className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
                Group:
              </label>
              <select
                id="group-filter"
                className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={filters.groupId}
                onChange={(e) => setFilters({ ...filters, groupId: e.target.value })}
              >
                <option value="">All Groups</option>
                {groups.map((group) => (
                  <option key={group.id} value={String(group.id)}>{group.name}</option>
                ))}
              </select>
              {filters.groupId && (
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, groupId: '' })}
                  className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                  title="Clear group filter"
                >
                  ✕
                </button>
              )}
            </div>
          )}
          
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
                {hasAdminKey && (
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider truncate">
                    Actions
                  </th>
                )}
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
                  {hasAdminKey && (
                    <td className="px-4 py-3 whitespace-nowrap text-sm">
                      <div className="flex items-center space-x-1">
                        <button
                          type="button"
                          onClick={() => handleDeleteHost(host.id)}
                          className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 p-1 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                          title="Delete host"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </td>
                  )}
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
              type="button"
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
              type="button"
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
                  type="button"
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
                      type="button"
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
                          type="button"
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
                          type="button"
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
                          type="button"
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
                  type="button"
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
