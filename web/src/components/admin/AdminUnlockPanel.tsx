import { AlertCircle, CheckCircle, Key, ShieldAlert, ShieldCheck } from 'lucide-react'

interface AdminUnlockPanelProps {
  apiKeyDraft: string
  isAuthorized: boolean
  sessionError: boolean
  message: { type: 'success' | 'error'; text: string } | null
  sessionErrorText: string | null
  onDraftChange: (value: string) => void
  onUnlock: () => void | Promise<void>
}

export default function AdminUnlockPanel({
  apiKeyDraft,
  isAuthorized,
  sessionError,
  message,
  sessionErrorText,
  onDraftChange,
  onUnlock,
}: AdminUnlockPanelProps) {
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
              Enter the shared admin API key to unlock scanner controls and workflow telemetry.
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

        {sessionError && sessionErrorText && (
          <div className="mt-6 rounded-xl bg-rose-50 p-4 text-sm text-rose-800 dark:bg-rose-900/20 dark:text-rose-200">
            {sessionErrorText}
          </div>
        )}

        <div className="mt-6 space-y-4">
          <label htmlFor="admin-api-key" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Shared Admin API Key
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Key className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                id="admin-api-key"
                type="password"
                value={apiKeyDraft}
                onChange={(event) => onDraftChange(event.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white py-3 pl-10 pr-4 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                placeholder="Enter admin key"
              />
            </div>
            <button
              type="button"
              onClick={() => void onUnlock()}
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
