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
import WorkflowListPanel from "../components/admin/WorkflowListPanel";
import WorkflowDetailPanel from "../components/admin/WorkflowDetailPanel";
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
    <div className="space-y-6 px-4 py-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Scanner Control Room
          </h2>
          <p className="mt-2 max-w-4xl text-sm text-gray-500 dark:text-gray-400">
            Workflow-first control room for continuous ACO scanning, one-off
            discovery runs, and the downstream jobs they create.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
            <RefreshCw
              className={`h-4 w-4 ${isFetching || jobsFetching || probeStatsFetching ? "animate-spin" : ""}`}
            />
            Polling admin state
          </div>
          <button
            type="button"
            onClick={handleLock}
            className="rounded-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Lock Admin
          </button>
        </div>
      </div>

      {message && (
        <div
          className={`flex items-center gap-3 rounded-xl p-4 text-sm ${
            message.type === "success"
              ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200"
              : "bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-200"
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

      <OverviewGrid cards={overviewCards} />

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

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
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

      <WorkflowHistoryPanel
        recentResults={recentResults}
        topBlocks={topBlocks}
        history={history}
      />

      <div className="space-y-6">
        <WorkflowListPanel
          workflows={workflowsData || []}
          onSelect={(wf) => setSelectedWorkflowId(wf.workflow_id)}
          selectedId={selectedWorkflowId}
        />

        {selectedWorkflow && (
          <WorkflowDetailPanel
            workflow={selectedWorkflow}
            onClose={() => setSelectedWorkflowId(null)}
          />
        )}
      </div>
    </div>
  );
}
