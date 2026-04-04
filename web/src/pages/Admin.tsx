import { useState } from "react";
import { useQuery } from "react-query";
import axios from "axios";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Database,
  Globe,
  Loader,
  Radar,
  RefreshCw,
} from "lucide-react";

import ScannerWorldMap from "../components/ScannerWorldMap";
import ScannerWorkbench from "../components/ScannerWorkbench";
import AdminUnlockPanel from "../components/admin/AdminUnlockPanel";
import HostGroupsPanel from "../components/admin/HostGroupsPanel";
import OverviewGrid from "../components/admin/OverviewGrid";
import CurrentWorkflowCard from "../components/admin/CurrentWorkflowCard";
import LiveLogsCard from "../components/admin/LiveLogsCard";
import ProbeSnapshotCard from "../components/admin/ProbeSnapshotCard";
import JobsPanel from "../components/admin/JobsPanel";
import WorkflowHistoryPanel from "../components/admin/WorkflowHistoryPanel";
import WorkflowRail from "../components/admin/WorkflowRail";
import EvidenceLedger from "../components/admin/EvidenceLedger";
import ExclusionsPanel from "../components/admin/ExclusionsPanel";
import type {
  AdminJobsResponse,
  DashboardResponse,
  CurrentLogsResponse,
  ProbeStatsResponse,
  WorkflowResponse,
  WorkflowDetailResponse,
} from "../components/admin/types";
import { numberFormatter } from "../components/admin/format";

import {
  clearStoredAdminApiKey,
  getStoredAdminApiKey,
  setStoredAdminApiKey,
} from "../lib/adminAuth";

const getErrorMessage = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    return (
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.message
    );
  }

  return error instanceof Error ? error.message : "Unknown error";
};

export default function Admin() {
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [apiKeyDraft, setApiKeyDraft] = useState(() => getStoredAdminApiKey());
  const [adminKey, setAdminKey] = useState(() => getStoredAdminApiKey());
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(
    null,
  );

  const {
    data: sessionData,
    isLoading: sessionLoading,
    isError: sessionError,
    error: sessionErrorValue,
    refetch: refetchSession,
  } = useQuery(
    ["admin-session", adminKey],
    async () => {
      const response = await axios.get("/api/admin/session");
      return response.data as { authorized: boolean };
    },
    {
      enabled: Boolean(adminKey),
      retry: false,
      refetchOnWindowFocus: false,
    },
  );

  const isAuthorized =
    Boolean(adminKey) && !sessionError && sessionData?.authorized === true;

  const { data, isLoading, isFetching, refetch } = useQuery(
    ["aco-dashboard"],
    async () => {
      const response = await axios.get("/api/aco/dashboard");
      return response.data as DashboardResponse;
    },
    {
      enabled: isAuthorized,
      refetchInterval: 5000,
      refetchIntervalInBackground: true,
    },
  );

  const {
    data: jobsData,
    isFetching: jobsFetching,
    refetch: refetchJobs,
  } = useQuery(
    ["admin-jobs"],
    async () => {
      const response = await axios.get("/api/admin/jobs?limit=80");
      return response.data as AdminJobsResponse;
    },
    {
      enabled: isAuthorized,
      refetchInterval: 3000,
      refetchIntervalInBackground: true,
    },
  );

  const {
    data: probeStats,
    isFetching: probeStatsFetching,
    refetch: refetchProbeStats,
  } = useQuery(
    ["probe-stats"],
    async () => {
      const response = await axios.get("/api/probe-stats?minutes=5");
      return response.data as ProbeStatsResponse;
    },
    {
      enabled: isAuthorized,
      refetchInterval: 5000,
      refetchIntervalInBackground: true,
    },
  );

  const {
    data: logData,
    isFetching: logsFetching,
    refetch: refetchLogs,
  } = useQuery(
    ["aco-current-logs"],
    async () => {
      const response = await axios.get("/api/aco/logs/current?lines=300");
      return response.data as CurrentLogsResponse;
    },
    {
      enabled: isAuthorized && showLogs,
      refetchInterval: showLogs ? 2000 : false,
      refetchIntervalInBackground: showLogs,
    },
  );

  const { data: workflowsData } = useQuery(
    ["admin-workflows"],
    async () => {
      const response = await axios.get("/api/admin/workflows?limit=50");
      return response.data as WorkflowResponse[];
    },
    {
      enabled: isAuthorized,
      refetchInterval: 5000,
      refetchIntervalInBackground: true,
    },
  );

  const { data: selectedWorkflow } = useQuery(
    ["admin-workflow", selectedWorkflowId],
    async () => {
      if (!selectedWorkflowId) return null;
      const response = await axios.get(
        `/api/admin/workflows/${selectedWorkflowId}`,
      );
      return response.data as WorkflowDetailResponse;
    },
    {
      enabled: isAuthorized && Boolean(selectedWorkflowId),
    },
  );

  const scheduler = data?.scheduler;
  const geography = data?.geography;
  const history = data?.history || [];
  const status = scheduler?.status || "not_running";
  const currentJob = scheduler?.current_job;
  const recentResults = scheduler?.recent_results || [];
  const topBlocks = scheduler?.top_blocks || [];
  const celeryJobs = jobsData?.jobs || [];
  const discoveredHosts =
    probeStats?.total_hosts ??
    ((geography?.known_hosts ?? 0) + (geography?.unknown_hosts ?? 0));

  const handleUnlock = async () => {
    const nextKey = apiKeyDraft.trim();
    if (!nextKey) {
      setMessage({
        type: "error",
        text: "Enter an admin API key to unlock the control room.",
      });
      return;
    }

    setStoredAdminApiKey(nextKey);
    setAdminKey(nextKey);
    setMessage(null);
    const result = await refetchSession();
    if (result.error) {
      setMessage({
        type: "error",
        text: `Unlock failed: ${getErrorMessage(result.error)}`,
      });
    }
  };

  const handleLock = () => {
    clearStoredAdminApiKey();
    setAdminKey("");
    setApiKeyDraft("");
    setMessage(null);
  };

  if (!adminKey || sessionLoading || (!isAuthorized && sessionError)) {
    return (
      <AdminUnlockPanel
        apiKeyDraft={apiKeyDraft}
        isAuthorized={isAuthorized}
        sessionError={sessionError}
        message={message}
        sessionErrorText={
          sessionError ? getErrorMessage(sessionErrorValue) : null
        }
        onDraftChange={setApiKeyDraft}
        onUnlock={handleUnlock}
      />
    );
  }

  if (isLoading || !scheduler || !geography) {
    return (
      <div className="flex justify-center py-16">
        <Loader className="h-10 w-10 animate-spin text-blue-600" />
      </div>
    );
  }

  const overviewCards = [
    {
      label: "Scheduler Status",
      value: status.replace("_", " "),
      detail: currentJob ? currentJob.cidr : "No block currently scanning",
      icon: Activity,
    },
    {
      label: "Blocks Scanned",
      value: `${numberFormatter.format(scheduler.stats.scanned_blocks)} / ${numberFormatter.format(
        scheduler.stats.total_blocks,
      )}`,
      detail: `${numberFormatter.format(scheduler.stats.unscanned_blocks)} still eligible`,
      icon: Radar,
    },
    {
      label: "Discovered Hosts",
      value: numberFormatter.format(discoveredHosts),
      detail: `${numberFormatter.format(scheduler.stats.total_yield)} ACO yield in scheduler memory`,
      icon: Database,
    },
    {
      label: "Geocoded Hosts",
      value: numberFormatter.format(geography.known_hosts),
      detail: `${numberFormatter.format(geography.unknown_hosts)} still missing geography`,
      icon: Globe,
    },
  ];

  return (
    <div className="flex h-[calc(100vh-64px)] gap-0 bg-[#0a0a0a]">
      {/* Surface 1: Workflow Rail (left) */}
      <aside className="hidden xl:flex w-80 flex-shrink-0 flex-col border-r border-gray-800">
        <WorkflowRail
          workflows={workflowsData || []}
          selectedId={selectedWorkflowId}
          onSelect={setSelectedWorkflowId}
        />
      </aside>

      {/* Center: Scanner Control Room */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="p-6 space-y-6">
          {/* Header + status strip */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-2xl font-bold text-white">
                Scanner Control Room
              </h2>
              <p className="mt-2 max-w-4xl text-sm text-gray-400">
                Workflow-first control room for continuous ACO scanning, one-off
                discovery runs, and the downstream jobs they create.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 rounded-full border border-gray-800 bg-[#111] px-3 py-2 text-sm text-gray-300">
                <RefreshCw
                  className={`h-4 w-4 ${isFetching || jobsFetching || probeStatsFetching ? "animate-spin" : ""}`}
                />
                Polling admin state
              </div>
              <button
                type="button"
                onClick={handleLock}
                className="rounded-full border border-gray-800 bg-[#111] px-3 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-800"
              >
                Lock Admin
              </button>
            </div>
          </div>

          {message && (
            <div
              className={`flex items-center gap-3 rounded-lg border p-4 text-sm ${
                message.type === "success"
                  ? "border-emerald-800 bg-emerald-900/20 text-emerald-200"
                  : "border-rose-800 bg-rose-900/20 text-rose-200"
              }`}
            >
              {message.type === "success" ? (
                <CheckCircle className="h-5 w-5" />
              ) : (
                <AlertCircle className="h-5 w-5" />
              )}
              <span>{message.text}</span>
            </div>
          )}

          {/* Overview KPIs */}
          <OverviewGrid cards={overviewCards} />

          {/* Control Console + Groups */}
          <ScannerWorkbench
            schedulerStatus={status}
            onRefresh={async () => {
              await Promise.all([refetch(), refetchJobs(), refetchProbeStats()]);
            }}
          />

          <HostGroupsPanel
            onChanged={async () => {
              await Promise.all([refetch(), refetchJobs(), refetchProbeStats()]);
            }}
          />

          {/* Constitutional Exclusions */}
          <ExclusionsPanel />

          {/* World Map */}
          <div className="rounded-lg border border-gray-800 bg-[#111] p-6">
            <ScannerWorldMap
              countries={geography.countries}
              knownHosts={geography.known_hosts}
              unknownHosts={geography.unknown_hosts}
              points={geography.points}
              blocks={geography.blocks}
              countryDetails={geography.country_details}
              blockPrefixLen={geography.block_prefix_len}
            />
          </div>

          {/* Current job / logs / probe stats / jobs */}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.78fr)_minmax(0,1.22fr)]">
            <div className="space-y-6">
              <CurrentWorkflowCard currentJob={currentJob} />
              <LiveLogsCard
                logData={logData}
                logsFetching={logsFetching}
                showLogs={showLogs}
                onToggleLogs={() => setShowLogs((prev) => !prev)}
                onRefreshLogs={() => void refetchLogs()}
              />
            </div>

            <div className="space-y-6">
              <ProbeSnapshotCard
                probeStats={probeStats}
                onRefresh={() => void refetchProbeStats()}
              />
              <JobsPanel
                workers={jobsData?.workers}
                jobs={celeryJobs}
                onRefresh={() => void refetchJobs()}
              />
            </div>
          </div>

          {/* Workflow history */}
          <WorkflowHistoryPanel
            recentResults={recentResults}
            topBlocks={topBlocks}
            history={history}
          />

          {/* Mobile / small-screen fallback for workflow list + detail */}
          <div className="space-y-6 xl:hidden">
            <div className="rounded-lg border border-gray-800 bg-[#111]">
              <div className="px-4 py-3 border-b border-gray-800">
                <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-gray-500">
                  Workflows
                </div>
              </div>
              <div className="p-4">
                {workflowsData && workflowsData.length > 0 ? (
                  <div className="space-y-2">
                    {workflowsData.slice(0, 5).map((wf) => (
                      <button
                        key={wf.workflow_id}
                        type="button"
                        onClick={() => setSelectedWorkflowId(wf.workflow_id)}
                        className={`w-full rounded-lg border p-3 text-left text-xs font-mono transition-colors ${
                          selectedWorkflowId === wf.workflow_id
                            ? "border-green-500 bg-green-900/15"
                            : "border-gray-800 hover:bg-gray-900"
                        }`}
                      >
                        <div className="flex justify-between gap-2">
                          <span className="text-gray-300 truncate">{wf.strategy} // {wf.target}</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] ${
                            wf.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' :
                            wf.status === 'running' ? 'bg-amber-500/20 text-amber-400' :
                            wf.status === 'failed' ? 'bg-rose-500/20 text-rose-400' :
                            'bg-gray-700 text-gray-400'
                          }`}>
                            {wf.status}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-gray-500 font-mono">No workflows yet</p>
                )}
              </div>
            </div>

            {selectedWorkflow && (
              <div className="rounded-lg border border-gray-800 bg-[#111] p-4">
                <div className="text-sm font-semibold text-white mb-2">
                  Workflow {selectedWorkflow.workflow_id.slice(0, 8)}
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  {selectedWorkflow.strategy} // {selectedWorkflow.target}
                </div>
                <div className="mt-2 text-xs text-gray-500">
                  Policy: {selectedWorkflow.policy_snapshot_hash?.slice(0, 16)}...
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Surface 4: Evidence Ledger (right) */}
      <aside className="hidden 2xl:flex w-[26rem] flex-shrink-0 border-l border-gray-800">
        {selectedWorkflow ? (
          <EvidenceLedger workflow={selectedWorkflow} />
        ) : (
          <div className="h-full flex flex-col bg-[#050505]">
            <div className="px-4 py-3 border-b border-gray-800">
              <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-gray-500">
                Evidence Ledger
              </div>
            </div>
            <div className="flex-1 flex items-center justify-center px-6">
              <p className="text-xs font-mono text-gray-500 text-center">
                Select a workflow from the rail to inspect its receipts, metrics, and evidence.
              </p>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}