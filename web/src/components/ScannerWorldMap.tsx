import { useEffect, useMemo, useRef, useState } from 'react'
import { geoMercator } from 'd3-geo'
import WorldMap from 'react-svg-worldmap'
import { Globe, MapIcon } from 'lucide-react'
import { useDarkMode } from '../contexts/DarkModeContext'
import { resolveCountryCounts, type CountryCount } from '../lib/countryLookup'

export interface HostPoint {
  ip: string
  country: string
  city: string
  lat: number
  lon: number
  status: string
}

interface ScannerWorldMapProps {
  countries: CountryCount[]
  knownHosts: number
  unknownHosts: number
  points?: HostPoint[]
}

interface ProjectedHostPoint extends HostPoint {
  x: number
  y: number
}

const numberFormatter = new Intl.NumberFormat()
const BASE_MAP_WIDTH = 960
const MAP_HEIGHT_RATIO = 0.7
const INNER_TRANSLATE_Y = 240
const MIN_MAP_WIDTH = 320

const getPointColor = (status: string) => {
  switch (status) {
    case 'online':
      return '#22c55e'
    case 'timeout':
      return '#f59e0b'
    case 'non_ollama':
      return '#94a3b8'
    default:
      return '#ef4444'
  }
}

export default function ScannerWorldMap({
  countries,
  knownHosts,
  unknownHosts,
  points = [],
}: ScannerWorldMapProps) {
  const { isDark } = useDarkMode()
  const { resolved, unresolved, mapData } = resolveCountryCounts(countries)
  const mapStageRef = useRef<HTMLDivElement>(null)
  const [mapWidth, setMapWidth] = useState(BASE_MAP_WIDTH)

  useEffect(() => {
    const element = mapStageRef.current
    if (!element) {
      return undefined
    }

    const updateSize = () => {
      const nextWidth = Math.max(MIN_MAP_WIDTH, Math.floor(element.getBoundingClientRect().width))
      setMapWidth(nextWidth)
    }

    updateSize()

    const resizeObserver = new ResizeObserver(() => {
      updateSize()
    })

    resizeObserver.observe(element)
    window.addEventListener('resize', updateSize)

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', updateSize)
    }
  }, [])

  const mapHeight = mapWidth * MAP_HEIGHT_RATIO

  const projectedPoints = useMemo<ProjectedHostPoint[]>(() => {
    if (points.length === 0) {
      return []
    }

    const projection = geoMercator()

    return points
      .map((point) => {
        const coordinates = projection([point.lon, point.lat])
        if (!coordinates) {
          return null
        }

        const [x, y] = coordinates
        return {
          ...point,
          x,
          y,
        }
      })
      .filter((point): point is ProjectedHostPoint => point !== null)
  }, [points])

  const overlayTransform = `scale(${mapWidth / BASE_MAP_WIDTH}) translate(0, ${INNER_TRANSLATE_Y})`

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Host Geography</h3>
            <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-200">
              {numberFormatter.format(resolved.length)} countries
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Geocoded hosts currently in the database, grouped by country and plotted by location.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
          <MapIcon className="h-4 w-4" />
          {numberFormatter.format(projectedPoints.length)} plotted points
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Geocoded Hosts</p>
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
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">Top Coverage</p>
          <p className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
            {resolved[0]
              ? `${resolved[0].flag} ${resolved[0].label} (${numberFormatter.format(resolved[0].count)})`
              : 'No countries mapped yet'}
          </p>
        </div>
      </div>

      {mapData.length > 0 ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_18rem]">
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-4 dark:border-gray-700">
            <div ref={mapStageRef} className="relative w-full min-w-0 overflow-hidden">
              <WorldMap
                color="#60a5fa"
                backgroundColor="transparent"
                borderColor={isDark ? '#334155' : '#94a3b8'}
                title=""
                valueSuffix="hosts"
                size={mapWidth}
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

              {projectedPoints.length > 0 && (
                <svg
                  className="pointer-events-none absolute left-0 top-0"
                  width={mapWidth}
                  height={mapHeight}
                  viewBox={`0 0 ${mapWidth} ${mapHeight}`}
                  aria-hidden="true"
                >
                  <g transform={overlayTransform}>
                    {projectedPoints.map((point) => {
                      const color = getPointColor(point.status)
                      return (
                        <g key={`${point.ip}-${point.lat}-${point.lon}`}>
                          <circle cx={point.x} cy={point.y} r={6} fill={color} opacity={0.18} />
                          <circle
                            cx={point.x}
                            cy={point.y}
                            r={3.2}
                            fill={color}
                            stroke="rgba(255,255,255,0.55)"
                            strokeWidth={0.8}
                          />
                        </g>
                      )
                    })}
                  </g>
                </svg>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <Globe className="h-4 w-4" />
              Top Countries
            </div>
            <div className="space-y-3 max-h-[28rem] overflow-y-auto">
              {resolved.slice(0, 10).map((item) => (
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
