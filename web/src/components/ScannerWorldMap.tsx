import { useEffect, useMemo, useRef, useState } from "react";
import { geoMercator } from "d3-geo";
import WorldMap from "react-svg-worldmap";
import { Globe, Layers3, MapIcon, MapPinned, Waypoints } from "lucide-react";

import { useDarkMode } from "../contexts/DarkModeContext";
import {
  resolveCountryCounts,
  resolveCountryMeta,
  type CountryCount,
} from "../lib/countryLookup";

export interface HostPoint {
  ip: string;
  country: string;
  city: string;
  lat: number;
  lon: number;
  status: string;
  kind?: "host" | "sampled";
}

export interface CountryDetail {
  country: string;
  host_count: number;
  online_host_count: number;
  sampled_ip_count: number;
  discovered_ip_count: number;
  block_count: number;
  ip_ranges: string[];
  ip_range_count: number;
  avg_lat: number | null;
  avg_lon: number | null;
  lat_min: number | null;
  lat_max: number | null;
  lon_min: number | null;
  lon_max: number | null;
  width_km: number;
  height_km: number;
  area_km2: number;
  radius_km: number;
}

export interface GeocodedBlock {
  cidr: string;
  country: string;
  prefix_len: number;
  ip_start: string;
  ip_end: string;
  host_count: number;
  online_host_count: number;
  sampled_ip_count: number;
  discovered_ip_count: number;
  sample_ips: string[];
  source: "hosts" | "scan-sampled" | "mixed";
  avg_lat: number | null;
  avg_lon: number | null;
  lat_min: number | null;
  lat_max: number | null;
  lon_min: number | null;
  lon_max: number | null;
  width_km: number;
  height_km: number;
  area_km2: number;
  radius_km: number;
}

interface ScannerWorldMapProps {
  countries: CountryCount[];
  knownHosts: number;
  unknownHosts: number;
  points?: HostPoint[];
  blocks?: GeocodedBlock[];
  countryDetails?: CountryDetail[];
  blockPrefixLen?: number | null;
}

interface ProjectedHostPoint extends HostPoint {
  x: number;
  y: number;
  isSelected: boolean;
}

interface ProjectedBlock extends GeocodedBlock {
  x: number;
  y: number;
  rx: number;
  ry: number;
  isCountrySelected: boolean;
  isBlockSelected: boolean;
}

const numberFormatter = new Intl.NumberFormat();
const BASE_MAP_WIDTH = 960;
const MAP_HEIGHT_RATIO = 0.7;
const INNER_TRANSLATE_Y = 240;
const MIN_MAP_WIDTH = 320;
const MIN_BLOCK_RX = 8;
const MIN_BLOCK_RY = 6;

const getPointColor = (status: string) => {
  switch (status) {
    case "online":
      return "#22c55e";
    case "timeout":
      return "#f59e0b";
    case "non_ollama":
      return "#94a3b8";
    case "sampled":
      return "#38bdf8";
    case "sampled-hit":
      return "#a78bfa";
    default:
      return "#ef4444";
  }
};

const formatLatLon = (lat: number | null, lon: number | null) =>
  lat === null || lon === null
    ? "Country-level only"
    : `${lat.toFixed(2)}, ${lon.toFixed(2)}`;

const clampRadius = (value: number, minimum: number) =>
  Number.isFinite(value) && value > minimum ? value : minimum;

export default function ScannerWorldMap({
  countries,
  knownHosts,
  unknownHosts,
  points = [],
  blocks = [],
  countryDetails = [],
  blockPrefixLen,
}: ScannerWorldMapProps) {
  const { isDark } = useDarkMode();
  const { resolved, unresolved, mapData } = resolveCountryCounts(countries);
  const mapStageRef = useRef<HTMLDivElement>(null);
  const [mapWidth, setMapWidth] = useState(BASE_MAP_WIDTH);
  const [selectedCountryCode, setSelectedCountryCode] = useState<string | null>(
    resolved[0]?.code ?? null,
  );
  const [selectedBlockCidr, setSelectedBlockCidr] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const element = mapStageRef.current;
    if (!element) {
      return undefined;
    }

    const updateSize = () => {
      const nextWidth = Math.max(
        MIN_MAP_WIDTH,
        Math.floor(element.getBoundingClientRect().width),
      );
      setMapWidth(nextWidth);
    };

    updateSize();

    const resizeObserver = new ResizeObserver(() => {
      updateSize();
    });

    resizeObserver.observe(element);
    window.addEventListener("resize", updateSize);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", updateSize);
    };
  }, []);

  useEffect(() => {
    if (resolved.length === 0) {
      setSelectedCountryCode(null);
      return;
    }

    if (!selectedCountryCode) {
      setSelectedCountryCode(resolved[0].code);
    }
  }, [resolved, selectedCountryCode]);

  const mapHeight = mapWidth * MAP_HEIGHT_RATIO;

  const projection = useMemo(() => geoMercator(), []);

  const selectedCodeUpper = selectedCountryCode?.toUpperCase() ?? null;

  const resolvedCountryByCode = useMemo(() => {
    const next = new Map<string, (typeof resolved)[number]>();
    resolved.forEach((country) => {
      next.set(country.code.toUpperCase(), country);
    });
    return next;
  }, [resolved]);

  const countryDetailByCode = useMemo(() => {
    const next = new Map<
      string,
      CountryDetail & {
        code: string;
        label: string;
        flag: string;
        region: string;
      }
    >();

    countryDetails.forEach((detail) => {
      const meta = resolveCountryMeta(detail.country);
      if (!meta) {
        return;
      }

      next.set(meta.code.toUpperCase(), {
        ...detail,
        ...meta,
      });
    });

    return next;
  }, [countryDetails]);

  const selectedCountryDetail = selectedCodeUpper
    ? (countryDetailByCode.get(selectedCodeUpper) ?? null)
    : null;

  const selectedCountryResolved = selectedCodeUpper
    ? (resolvedCountryByCode.get(selectedCodeUpper) ?? null)
    : null;

  const projectedPoints = useMemo<ProjectedHostPoint[]>(() => {
    return points
      .map((point) => {
        const coordinates = projection([point.lon, point.lat]);
        if (!coordinates) {
          return null;
        }

        const [x, y] = coordinates;
        const countryMeta = resolveCountryMeta(point.country);
        const pointCountryCode = countryMeta?.code.toUpperCase() ?? null;

        return {
          ...point,
          x,
          y,
          isSelected: Boolean(
            selectedCodeUpper && pointCountryCode === selectedCodeUpper,
          ),
        };
      })
      .filter((point): point is ProjectedHostPoint => point !== null);
  }, [points, projection, selectedCodeUpper]);

  const projectedBlocks = useMemo<ProjectedBlock[]>(() => {
    return blocks
      .map((block) => {
        if (
          block.avg_lat === null ||
          block.avg_lon === null ||
          block.lat_min === null ||
          block.lat_max === null ||
          block.lon_min === null ||
          block.lon_max === null
        ) {
          return null;
        }

        const center = projection([block.avg_lon, block.avg_lat]);
        if (!center) {
          return null;
        }

        const east = projection([block.lon_max, block.avg_lat]);
        const west = projection([block.lon_min, block.avg_lat]);
        const north = projection([block.avg_lon, block.lat_max]);
        const south = projection([block.avg_lon, block.lat_min]);

        const [x, y] = center;
        const densityMetric = Math.max(
          block.sampled_ip_count,
          block.host_count,
          1,
        );
        const rx = clampRadius(
          Math.max(
            Math.abs((east?.[0] ?? x) - x),
            Math.abs((west?.[0] ?? x) - x),
            densityMetric > 1 ? Math.log2(densityMetric + 1) * 2 : 0,
          ),
          MIN_BLOCK_RX,
        );
        const ry = clampRadius(
          Math.max(
            Math.abs((north?.[1] ?? y) - y),
            Math.abs((south?.[1] ?? y) - y),
            densityMetric > 1 ? Math.log2(densityMetric + 1) * 1.5 : 0,
          ),
          MIN_BLOCK_RY,
        );

        const countryMeta = resolveCountryMeta(block.country);
        const blockCountryCode = countryMeta?.code.toUpperCase() ?? null;

        return {
          ...block,
          x,
          y,
          rx,
          ry,
          isCountrySelected: Boolean(
            selectedCodeUpper && blockCountryCode === selectedCodeUpper,
          ),
          isBlockSelected: block.cidr === selectedBlockCidr,
        };
      })
      .filter((block): block is ProjectedBlock => block !== null);
  }, [blocks, projection, selectedBlockCidr, selectedCodeUpper]);

  const selectedBlocks = useMemo(() => {
    if (!selectedCodeUpper) {
      return [];
    }

    return blocks.filter((block) => {
      const countryMeta = resolveCountryMeta(block.country);
      return countryMeta?.code.toUpperCase() === selectedCodeUpper;
    });
  }, [blocks, selectedCodeUpper]);

  useEffect(() => {
    if (selectedBlocks.length === 0) {
      setSelectedBlockCidr(null);
      return;
    }

    if (
      !selectedBlockCidr ||
      !selectedBlocks.some((block) => block.cidr === selectedBlockCidr)
    ) {
      setSelectedBlockCidr(selectedBlocks[0]?.cidr ?? null);
    }
  }, [selectedBlockCidr, selectedBlocks]);

  const sampledPointCount = useMemo(
    () => points.filter((point) => point.kind === "sampled").length,
    [points],
  );

  const overlayTransform = `scale(${mapWidth / BASE_MAP_WIDTH}) translate(0, ${INNER_TRANSLATE_Y})`;

  const highlightedCountryLabel =
    selectedCountryDetail?.label ??
    selectedCountryResolved?.label ??
    (selectedCodeUpper ? selectedCodeUpper : "No country selected");

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Geography Theater
            </h3>
            <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-200">
              Mercator projection
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Always-on world map with discovered host points, sampled scan IP
            locations, country aggregates, and IP block centroids sized by their
            observed geographic spread.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
          <Layers3 className="h-4 w-4" />/{blockPrefixLen ?? "—"} block
          subdivision · {numberFormatter.format(unknownHosts)} unknown hosts
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
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
            Scanned Blocks
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
            {numberFormatter.format(blocks.length)}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Geocoded Scan Points
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
            {numberFormatter.format(sampledPointCount)}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Mapped Countries
          </p>
          <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-white">
            {numberFormatter.format(resolved.length)}
          </p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(22rem,0.95fr)]">
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4 dark:border-gray-700">
          <div
            ref={mapStageRef}
            className="relative w-full min-w-0 overflow-hidden rounded-lg"
          >
            <WorldMap
              color="#60a5fa"
              backgroundColor="transparent"
              borderColor={isDark ? "#334155" : "#94a3b8"}
              title=""
              valueSuffix="observations"
              size={mapWidth}
              tooltipBgColor="#020617"
              tooltipTextColor="#f8fafc"
              data={mapData}
              onClickFunction={({ countryCode }) =>
                setSelectedCountryCode(countryCode)
              }
              tooltipTextFunction={({ countryName, countryValue }) =>
                countryValue
                  ? `${countryName}: ${numberFormatter.format(countryValue)} mapped scan observations`
                  : `${countryName}: no mapped scan observations yet`
              }
              styleFunction={({ countryCode, countryValue }) => {
                const isSelected =
                  selectedCodeUpper !== null &&
                  countryCode.toUpperCase() === selectedCodeUpper;

                return {
                  fillOpacity: isSelected ? 0.95 : countryValue ? 0.72 : 0.18,
                  strokeWidth: isSelected ? 1.6 : countryValue ? 0.9 : 0.5,
                  stroke: isSelected
                    ? "#e2e8f0"
                    : isDark
                      ? "#334155"
                      : "#94a3b8",
                  cursor: "pointer",
                  transition: "all 160ms ease",
                };
              }}
            />

            <svg
              className="absolute left-0 top-0"
              width={mapWidth}
              height={mapHeight}
              viewBox={`0 0 ${mapWidth} ${mapHeight}`}
              aria-hidden="true"
            >
              <g transform={overlayTransform}>
                {projectedBlocks.map((block) => (
                  <g
                    key={`${block.country}-${block.cidr}`}
                    opacity={block.isCountrySelected ? 1 : 0.46}
                    onClick={() => {
                      const meta = resolveCountryMeta(block.country);
                      if (meta) {
                        setSelectedCountryCode(meta.code);
                      }
                      setSelectedBlockCidr(block.cidr);
                    }}
                  >
                    <ellipse
                      cx={block.x}
                      cy={block.y}
                      rx={block.rx}
                      ry={block.ry}
                      fill={
                        block.isBlockSelected
                          ? "rgba(196, 181, 253, 0.38)"
                          : block.source === "scan-sampled"
                            ? "rgba(250, 204, 21, 0.16)"
                            : block.isCountrySelected
                              ? "rgba(96, 165, 250, 0.32)"
                              : "rgba(56, 189, 248, 0.16)"
                      }
                      stroke={
                        block.isBlockSelected
                          ? "#ddd6fe"
                          : block.source === "scan-sampled"
                            ? "rgba(250, 204, 21, 0.78)"
                            : block.isCountrySelected
                              ? "#bfdbfe"
                              : "rgba(147, 197, 253, 0.6)"
                      }
                      strokeWidth={
                        block.isBlockSelected
                          ? 1.8
                          : block.isCountrySelected
                            ? 1.4
                            : 0.8
                      }
                      style={{ cursor: "pointer" }}
                    />
                    <circle
                      cx={block.x}
                      cy={block.y}
                      r={
                        block.isBlockSelected
                          ? 4.5
                          : block.isCountrySelected
                            ? 3.8
                            : 2.8
                      }
                      fill={
                        block.isBlockSelected
                          ? "#ede9fe"
                          : block.source === "scan-sampled"
                            ? "#facc15"
                            : block.isCountrySelected
                              ? "#e0f2fe"
                              : "#7dd3fc"
                      }
                    />
                  </g>
                ))}

                {projectedPoints.map((point) => {
                  const color = getPointColor(point.status);
                  return (
                    <g
                      key={`${point.ip}-${point.lat}-${point.lon}`}
                      opacity={
                        point.isSelected || !selectedCodeUpper ? 1 : 0.35
                      }
                    >
                      <circle
                        cx={point.x}
                        cy={point.y}
                        r={point.isSelected ? 5.5 : 4.5}
                        fill={color}
                        opacity={0.18}
                      />
                      <circle
                        cx={point.x}
                        cy={point.y}
                        r={point.isSelected ? 3.3 : 2.6}
                        fill={color}
                        stroke="rgba(255,255,255,0.6)"
                        strokeWidth={0.8}
                      />
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <div className="rounded-lg border border-slate-700/70 bg-slate-900/80 p-3 text-sm text-slate-200">
              <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                <Waypoints className="h-4 w-4" />
                Block Averages
              </div>
              <p className="text-xs text-slate-300">
                Ellipses show scanned block centroids and observed spread. Gold
                blocks are scan-sampled footprints even when they produced no
                discovered hosts.
              </p>
            </div>
            <div className="rounded-lg border border-slate-700/70 bg-slate-900/80 p-3 text-sm text-slate-200">
              <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                <MapPinned className="h-4 w-4" />
                Host Points
              </div>
              <p className="text-xs text-slate-300">
                Green = online, amber = timeout, sky = sampled IP geography,
                violet = sampled IP that produced a hit.
              </p>
            </div>
            <div className="rounded-lg border border-slate-700/70 bg-slate-900/80 p-3 text-sm text-slate-200">
              <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                <Globe className="h-4 w-4" />
                Country Drilldown
              </div>
              <p className="text-xs text-slate-300">
                Click a country on the map or in the list to inspect its IP
                ranges and block subdivisions.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <MapIcon className="h-4 w-4" />
              Country Detail
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {selectedCountryDetail?.flag ??
                      selectedCountryResolved?.flag ??
                      "🌐"}{" "}
                    {highlightedCountryLabel}
                  </p>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {selectedCountryDetail?.region ??
                      selectedCountryResolved?.region ??
                      "No mapped region"}
                  </p>
                </div>
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-200">
                  {selectedBlocks.length} blocks
                </span>
              </div>

              {selectedCountryDetail ? (
                <div className="mt-4 space-y-4">
                  <dl className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/50">
                      <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Hosts
                      </dt>
                      <dd className="mt-2 text-lg font-semibold text-gray-900 dark:text-white">
                        {numberFormatter.format(
                          selectedCountryDetail.host_count,
                        )}
                      </dd>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/50">
                      <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Sampled IPs
                      </dt>
                      <dd className="mt-2 text-lg font-semibold text-gray-900 dark:text-white">
                        {numberFormatter.format(
                          selectedCountryDetail.sampled_ip_count,
                        )}
                      </dd>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/50">
                      <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Blocks
                      </dt>
                      <dd className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                        {numberFormatter.format(
                          selectedCountryDetail.block_count,
                        )}
                      </dd>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/50">
                      <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Average Location
                      </dt>
                      <dd className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                        {formatLatLon(
                          selectedCountryDetail.avg_lat,
                          selectedCountryDetail.avg_lon,
                        )}
                      </dd>
                    </div>
                  </dl>

                  <div>
                    <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                      IP ranges associated with this country
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {selectedCountryDetail.ip_ranges.length > 0 ? (
                        selectedCountryDetail.ip_ranges.map((range) => (
                          <span
                            key={range}
                            className="rounded-full border border-gray-200 bg-white px-2.5 py-1 font-mono text-xs text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200"
                          >
                            {range}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          No mapped scan ranges captured yet.
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="mt-4 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
                  Click a country with mapped scan observations to inspect the
                  IP ranges and block subdivisions in that region.
                </div>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <Layers3 className="h-4 w-4" />
              Blocks in {highlightedCountryLabel}
            </div>
            <div className="max-h-[26rem] space-y-3 overflow-y-auto">
              {selectedBlocks.length > 0 ? (
                selectedBlocks.map((block) => (
                  <button
                    key={`${block.country}-${block.cidr}`}
                    type="button"
                    onClick={() => setSelectedBlockCidr(block.cidr)}
                    className={`w-full rounded-lg border p-4 text-left dark:bg-gray-800 ${
                      block.cidr === selectedBlockCidr
                        ? "border-blue-400 bg-blue-50 dark:border-blue-500 dark:bg-blue-900/20"
                        : "border-gray-200 bg-white dark:border-gray-700"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-sm font-semibold text-gray-900 dark:text-white">
                        {block.cidr}
                      </p>
                      <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 dark:bg-sky-900/20 dark:text-sky-200">
                        {numberFormatter.format(
                          Math.max(block.sampled_ip_count, block.host_count),
                        )}{" "}
                        {block.sampled_ip_count > 0 ? "sampled IPs" : "hosts"}
                      </span>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-gray-600 dark:text-gray-300">
                      <p>
                        <span className="font-medium text-gray-900 dark:text-white">
                          Source:
                        </span>{" "}
                        {block.source === "scan-sampled"
                          ? "Scanned footprint"
                          : block.source === "mixed"
                            ? "Scanned + discovered"
                            : "Discovered hosts"}
                      </p>
                      <p>
                        <span className="font-medium text-gray-900 dark:text-white">
                          Average:
                        </span>{" "}
                        {formatLatLon(block.avg_lat, block.avg_lon)}
                      </p>
                      <p>
                        <span className="font-medium text-gray-900 dark:text-white">
                          Area:
                        </span>{" "}
                        {block.avg_lat === null || block.avg_lon === null
                          ? "No coordinate cluster yet"
                          : `${numberFormatter.format(Math.round(block.area_km2))} km² (${numberFormatter.format(Math.round(block.width_km))} × ${numberFormatter.format(Math.round(block.height_km))} km)`}
                      </p>
                      <p>
                        <span className="font-medium text-gray-900 dark:text-white">
                          Discovered IPs:
                        </span>{" "}
                        {numberFormatter.format(block.discovered_ip_count)}
                      </p>
                      <p>
                        <span className="font-medium text-gray-900 dark:text-white">
                          IP span:
                        </span>{" "}
                        <span className="font-mono">{block.ip_start}</span> →{" "}
                        <span className="font-mono">{block.ip_end}</span>
                      </p>
                      {block.sample_ips.length > 0 && (
                        <p>
                          <span className="font-medium text-gray-900 dark:text-white">
                            Sample IPs:
                          </span>{" "}
                          {block.sample_ips.join(", ")}
                        </p>
                      )}
                    </div>
                  </button>
                ))
              ) : (
                <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
                  No scanned blocks available for the selected country yet.
                </div>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/50">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <Globe className="h-4 w-4" />
              Top Countries
            </div>
            <div className="space-y-3 max-h-[20rem] overflow-y-auto">
              {resolved.slice(0, 12).map((item) => {
                const isSelected =
                  item.code.toUpperCase() === selectedCodeUpper;
                return (
                  <button
                    key={`${item.code}-${item.country}`}
                    type="button"
                    onClick={() => setSelectedCountryCode(item.code)}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                      isSelected
                        ? "border-blue-400 bg-blue-50 dark:border-blue-500 dark:bg-blue-900/20"
                        : "border-gray-200 bg-white hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700"
                    }`}
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-900 dark:text-white">
                        {item.flag} {item.label}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {item.region}
                      </p>
                    </div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {numberFormatter.format(item.count)}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {resolved.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/30 dark:text-gray-400">
          The Mercator world map is live, but there are no mapped hosts or scan
          footprints yet.
        </div>
      )}

      {unresolved.length > 0 && (
        <p className="text-xs text-amber-600 dark:text-amber-300">
          {numberFormatter.format(unresolved.length)} country labels could not
          be mapped to ISO codes.
        </p>
      )}
    </div>
  );
}
