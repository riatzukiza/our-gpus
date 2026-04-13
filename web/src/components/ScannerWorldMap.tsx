import WorldMap from 'react-svg-worldmap'
import { Globe, MapIcon } from 'lucide-react'
import { useDarkMode } from '../contexts/DarkModeContext'
import { resolveCountryCounts, type CountryCount } from '../lib/countryLookup'

interface ScannerWorldMapProps {
  countries: CountryCount[]
  knownHosts: number
  unknownHosts: number
}

const numberFormatter = new Intl.NumberFormat()

export default function ScannerWorldMap({
  countries,
  knownHosts,
  unknownHosts,
}: ScannerWorldMapProps) {
  const { isDark } = useDarkMode()
  const { resolved, unresolved, mapData } = resolveCountryCounts(countries)

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Host Geography</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Geocoded hosts currently in the database, grouped by country.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-200">
          <MapIcon className="h-4 w-4" />
          {numberFormatter.format(resolved.length)} mapped countries
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Geocoded Hosts
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
            {numberFormatter.format(knownHosts)}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Unknown Geography
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
            {numberFormatter.format(unknownHosts)}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Top Coverage
          </p>
          <p className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
            {resolved[0]
              ? `${resolved[0].flag} ${resolved[0].label} (${numberFormatter.format(resolved[0].count)})`
              : 'No countries mapped yet'}
          </p>
        </div>
      </div>

      {mapData.length > 0 ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-4 dark:border-gray-700">
            <WorldMap
              color="#60a5fa"
              backgroundColor="transparent"
              borderColor={isDark ? '#334155' : '#94a3b8'}
              title="Discovered Host Geography"
              valueSuffix="hosts"
              size="responsive"
              richInteraction
              tooltipBgColor="#020617"
              tooltipTextColor="#f8fafc"
              data={mapData}
              styleFunction={({ countryValue }) => ({
                fillOpacity: countryValue ? 0.95 : 0.18,
                strokeWidth: countryValue ? 0.9 : 0.5,
                cursor: countryValue ? 'pointer' : 'default',
                transition: 'all 160ms ease',
              })}
            />
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <Globe className="h-4 w-4" />
              Top Countries
            </div>
            <div className="space-y-3">
              {resolved.slice(0, 8).map((item) => (
                <div
                  key={`${item.code}-${item.country}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-gray-800"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-gray-900 dark:text-white">
                      {item.flag} {item.label}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{item.region}</p>
                  </div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">
                    {numberFormatter.format(item.count)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/30 dark:text-gray-400">
          No geocoded hosts are available for the map yet.
        </div>
      )}

      {unresolved.length > 0 && (
        <p className="text-xs text-amber-600 dark:text-amber-300">
          {numberFormatter.format(unresolved.length)} country labels could not be mapped to ISO codes.
        </p>
      )}
    </div>
  )
}
