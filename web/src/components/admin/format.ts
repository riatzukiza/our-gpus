import { format, formatDistanceToNowStrict } from "date-fns";

import type { CeleryJob, DashboardStatus } from "./types";

export const numberFormatter = new Intl.NumberFormat();

const hasExplicitTimezone = (value: string) =>
  /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(value);

const parseApiDate = (value: string | null) => {
  if (!value) {
    return null;
  }

  const normalized = hasExplicitTimezone(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

export const statusClasses: Record<DashboardStatus, string> = {
  running:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200",
  stopping:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200",
  stopped: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
  not_running:
    "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
  initializing:
    "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200",
};

export const resultClasses = (success: boolean) =>
  success
    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200"
    : "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200";

export const jobStatusClasses: Record<string, string> = {
  queued: "bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
  started: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200",
  success:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200",
  failure: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200",
};

export const formatTimestamp = (value: string | null) =>
  (() => {
    const parsed = parseApiDate(value);
    return parsed ? format(parsed, "MMM d, yyyy HH:mm:ss") : "Never";
  })();

export const formatAge = (value: string | null) =>
  (() => {
    const parsed = parseApiDate(value);
    return parsed
      ? formatDistanceToNowStrict(parsed, { addSuffix: true })
      : "Never";
  })();

export const formatDurationMs = (value: number) =>
  value >= 60_000
    ? `${(value / 60_000).toFixed(1)}m`
    : `${Math.max(1, Math.round(value / 1000))}s`;

export const formatSeconds = (value: number | null) => {
  if (value == null) {
    return "n/a";
  }
  if (value >= 3600) {
    return `${(value / 3600).toFixed(1)}h`;
  }
  if (value >= 60) {
    return `${(value / 60).toFixed(1)}m`;
  }
  return `${Math.round(value)}s`;
};

export const formatProgressPercent = (job: CeleryJob) => {
  if (job.total_items <= 0) {
    return job.status === "success" ? 100 : 0;
  }
  return Math.min(
    100,
    Math.round((job.processed_items / job.total_items) * 100),
  );
};

export const getJobCounts = (job: CeleryJob) => {
  const payload = job.payload || {};
  const statusCounts =
    (payload.status_counts as Record<string, number> | undefined) || {};
  const geocodeCounts =
    (payload.geocode_counts as Record<string, number> | undefined) || {};
  return { statusCounts, geocodeCounts };
};
