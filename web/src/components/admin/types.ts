import type { CountryCount } from "../../lib/countryLookup";
import type {
  CountryDetail,
  GeocodedBlock,
  HostPoint,
} from "../ScannerWorldMap";

export type DashboardStatus =
  | "running"
  | "stopping"
  | "stopped"
  | "not_running"
  | "initializing";

export interface SchedulerStats {
  total_blocks: number;
  scanned_blocks: number;
  unscanned_blocks: number;
  total_yield: number;
  avg_pheromone: number;
}

export interface CurrentJob {
  cidr: string;
  scan_uuid: string;
  started_at: string;
  output_file: string;
  log_file: string;
  port: string;
  rate: number;
  estimated_duration_s: number;
}

export interface RecentResult {
  cidr: string;
  scan_uuid: string;
  started_at: string;
  completed_at: string;
  output_file: string;
  log_file: string;
  hosts_found: number;
  duration_ms: number;
  success: boolean;
  error: string | null;
}

export interface TopBlock {
  cidr: string;
  pheromone: number;
  scan_count: number;
  cumulative_yield: number;
  last_scan: string | null;
}

export interface SchedulerSnapshot {
  status: DashboardStatus;
  started_at: string | null;
  uptime_seconds: number | null;
  prefix_len: number | null;
  estimated_block_duration_s: number | null;
  config: {
    port: string;
    rate: number;
    max_block_duration_s: number;
    min_scan_interval_s: number;
    breathing_room_s?: number;
    router_mac?: string;
    interface?: string;
    exclude_file?: string;
    aco_alpha?: number;
    aco_beta?: number;
    aco_decay?: number;
    aco_reinforcement?: number;
    aco_penalty?: number;
  } | null;
  stats: SchedulerStats;
  current_job: CurrentJob | null;
  recent_results: RecentResult[];
  top_blocks: TopBlock[];
  last_error: string | null;
}

export interface HistoryEntry {
  scan_id: number;
  cidr: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  hosts_found: number;
  failed_rows: number;
  processed_rows: number;
  error_message: string | null;
}

export interface GeographySummary {
  known_hosts: number;
  unknown_hosts: number;
  countries: CountryCount[];
  points?: HostPoint[];
  blocks?: GeocodedBlock[];
  country_details?: CountryDetail[];
  block_prefix_len?: number | null;
}

export interface DashboardResponse {
  status: DashboardStatus;
  scheduler: SchedulerSnapshot;
  history: HistoryEntry[];
  geography: GeographySummary;
}

export interface CurrentLogsResponse {
  status: "running" | "idle" | "not_running";
  scan?: {
    cidr: string;
    scan_uuid: string;
    started_at: string;
    port: string;
    rate: number;
    estimated_duration_s: number;
  };
  log_file?: string;
  lines?: number;
  logs?: string;
  message?: string;
  last_error?: string | null;
}

export interface ProbeStatsResponse {
  total_hosts: number;
  probes_completed: number;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number | null;
  error_count: number;
  timeout_count: number;
  host_status_breakdown: Record<string, number>;
  sample_errors: string[];
}

export interface WorkflowResponse {
  workflow_id: string;
  scan_id: number | null;
  workflow_kind: string;
  target: string;
  port: string;
  strategy: string;
  status: string;
  current_stage: string | null;
  operator_id: string | null;
  exclude_snapshot_hash: string;
  policy_snapshot_hash: string;
  parent_workflow_id: string | null;
  requested_config: Record<string, unknown>;
  summary: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkflowReceiptResponse {
  receipt_id: string;
  workflow_id: string;
  stage_name: string;
  status: string;
  operator_id: string | null;
  input_refs: string[];
  output_refs: string[];
  metrics: Record<string, unknown>;
  evidence_refs: string[];
  policy_decisions: string[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface WorkflowDetailResponse extends WorkflowResponse {
  receipts: WorkflowReceiptResponse[];
}

export interface WorkerInfo {
  name: string;
  online: boolean;
  active_count: number;
  reserved_count: number;
  scheduled_count: number;
}

export interface CeleryJob {
  task_id: string;
  kind: string;
  label: string | null;
  status: string;
  celery_state: string;
  total_items: number;
  processed_items: number;
  success_items: number;
  failed_items: number;
  message: string | null;
  error: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AdminJobsResponse {
  workers: {
    workers: WorkerInfo[];
    totals: {
      workers: number;
      active: number;
      reserved: number;
      scheduled: number;
    };
  };
  summary: Record<string, Record<string, number>>;
  jobs: CeleryJob[];
}
