import { useEffect, useState } from 'react'
import { useQuery } from 'react-query'
import axios from 'axios'
import { AlertCircle, CheckCircle, Loader, Plus, Trash2 } from 'lucide-react'

interface HostGroup {
  id: number
  name: string
  description: string | null
  country_filter: string | null
  system_filter: string | null
  host_count: number
}

interface HostGroupsPanelProps {
  onChanged: () => Promise<unknown>
}

const inputClassName =
  'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white'

const getErrorMessage = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail || error.response?.data?.message || error.message
  }
  return error instanceof Error ? error.message : 'Unknown error'
}

export default function HostGroupsPanel({ onChanged }: HostGroupsPanelProps) {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [form, setForm] = useState({
    name: '',
    description: '',
    countryFilter: '',
    systemFilter: '',
  })

  const { data: groups = [], refetch: refetchGroups, isLoading } = useQuery(
    ['admin-host-groups'],
    async () => {
      const response = await axios.get('/api/admin/groups')
      return response.data as HostGroup[]
    },
    {
      refetchOnWindowFocus: false,
    }
  )

  const { data: countries = [] } = useQuery(
    ['host-countries-admin'],
    async () => {
      const response = await axios.get('/api/hosts/countries')
      return response.data.countries as string[]
    },
    {
      refetchOnWindowFocus: false,
    }
  )

  useEffect(() => {
    if (!message) {
      return
    }
    const timeout = setTimeout(() => setMessage(null), 4000)
    return () => clearTimeout(timeout)
  }, [message])

  const updateField = (key: keyof typeof form, value: string) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const handleCreateGroup = async () => {
    if (!form.name.trim()) {
      setMessage({ type: 'error', text: 'Group name is required.' })
      return
    }
    setSaving(true)
    try {
      await axios.post('/api/admin/groups', {
        name: form.name.trim(),
        description: form.description.trim() || null,
        country_filter: form.countryFilter || null,
        system_filter: form.systemFilter || null,
        host_ids: [],
      })
      setForm({ name: '', description: '', countryFilter: '', systemFilter: '' })
      await Promise.all([refetchGroups(), onChanged()])
      setMessage({ type: 'success', text: 'Host group created.' })
    } catch (error) {
      setMessage({ type: 'error', text: `Failed to create group: ${getErrorMessage(error)}` })
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteGroup = async (groupId: number) => {
    setDeletingId(groupId)
    try {
      await axios.delete(`/api/admin/groups/${groupId}`)
      await Promise.all([refetchGroups(), onChanged()])
      setMessage({ type: 'success', text: 'Host group deleted.' })
    } catch (error) {
      setMessage({ type: 'error', text: `Failed to delete group: ${getErrorMessage(error)}` })
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Host Groups</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Save named collections of hosts and geography/system rules for quick operational filtering.
          </p>
        </div>
      </div>

      <div className="mt-5 rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm text-gray-600 dark:text-gray-300">
            <span className="mb-1 block">Group name</span>
            <input value={form.name} onChange={(event) => updateField('name', event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm text-gray-600 dark:text-gray-300">
            <span className="mb-1 block">Description</span>
            <input value={form.description} onChange={(event) => updateField('description', event.target.value)} className={inputClassName} />
          </label>
          <label className="text-sm text-gray-600 dark:text-gray-300">
            <span className="mb-1 block">Country filter</span>
            <select value={form.countryFilter} onChange={(event) => updateField('countryFilter', event.target.value)} className={inputClassName}>
              <option value="">None</option>
              {countries.map((country) => (
                <option key={country} value={country}>{country}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-gray-600 dark:text-gray-300">
            <span className="mb-1 block">System filter</span>
            <select value={form.systemFilter} onChange={(event) => updateField('systemFilter', event.target.value)} className={inputClassName}>
              <option value="">None</option>
              <option value="gpu">GPU</option>
              <option value="cpu">CPU</option>
            </select>
          </label>
        </div>

        <button
          type="button"
          onClick={handleCreateGroup}
          disabled={saving}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
        >
          {saving ? <Loader className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Create Group
        </button>
      </div>

      {message && (
        <div
          className={`mt-4 flex items-center gap-3 rounded-xl p-4 text-sm ${
            message.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200'
              : 'bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-200'
          }`}
        >
          {message.type === 'success' ? <CheckCircle className="h-5 w-5" /> : <AlertCircle className="h-5 w-5" />}
          <span>{message.text}</span>
        </div>
      )}

      <div className="mt-5 space-y-3">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader className="h-6 w-6 animate-spin text-blue-600" />
          </div>
        ) : groups.length > 0 ? (
          groups.map((group) => (
            <div key={group.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-gray-900 dark:text-white">{group.name}</p>
                  {group.description && <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{group.description}</p>}
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
                    {group.country_filter && <span className="rounded-full bg-white px-2.5 py-1 dark:bg-gray-800">Country: {group.country_filter}</span>}
                    {group.system_filter && <span className="rounded-full bg-white px-2.5 py-1 dark:bg-gray-800">System: {group.system_filter}</span>}
                    <span className="rounded-full bg-white px-2.5 py-1 dark:bg-gray-800">Hosts: {group.host_count}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void handleDeleteGroup(group.id)}
                  disabled={deletingId === group.id}
                  className="rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-900/20"
                >
                  {deletingId === group.id ? <Loader className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
            No host groups yet.
          </div>
        )}
      </div>
    </div>
  )
}
