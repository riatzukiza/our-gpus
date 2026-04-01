import { useEffect, useMemo, useState } from "react";
import { useQuery } from "react-query";
import axios from "axios";
import {
  AlertCircle,
  Briefcase,
  Building2,
  CheckCircle2,
  CircleDot,
  FileSearch,
  Loader,
  Mail,
  Plus,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Sparkles,
  Target,
  Upload,
} from "lucide-react";
import { format, formatDistanceToNow } from "date-fns";

import AdminUnlockPanel from "../components/admin/AdminUnlockPanel";
import type {
  AssetImportResponse,
  CampaignClusterResponse,
  EnrichmentRunResponse,
  JobQueuedResponse,
  LeadRecordResponse,
  LeadStatus,
  PaginatedLeadRecordResponse,
  RecommendedRoute,
} from "../components/leads/types";
import {
  clearStoredAdminApiKey,
  getStoredAdminApiKey,
  setStoredAdminApiKey,
} from "../lib/adminAuth";

const numberFormatter = new Intl.NumberFormat();

const inputClassName =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white";

const textareaClassName = `${inputClassName} min-h-[120px] font-mono`;

const parseNumber = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
};

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

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  try {
    return format(new Date(value), "MMM d, yyyy HH:mm");
  } catch {
    return value;
  }
};

const formatRelative = (value?: string | null) => {
  if (!value) return "—";
  try {
    return `${formatDistanceToNow(new Date(value), { addSuffix: true })}`;
  } catch {
    return value;
  }
};

const assetLabel = (lead: Pick<LeadRecordResponse, "asset">) => {
  const asset = lead.asset;
  if (!asset) return "Unknown asset";
  const identity = asset.domain || asset.hostname || asset.ip || asset.id;
  if (asset.port) {
    return `${identity}:${asset.port}`;
  }
  return identity;
};

const routeLabel = (route?: RecommendedRoute | null) => {
  if (!route) return "manual review";
  return route.replace(/_/g, " ");
};

const statusClassName = (status?: string | null) => {
  switch (status) {
    case "approved":
    case "completed":
    case "ok":
      return "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-200 dark:ring-emerald-800";
    case "reviewed":
    case "running":
      return "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-900/30 dark:text-blue-200 dark:ring-blue-800";
    case "suppressed":
    case "not_found":
    case "skipped":
      return "bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:ring-gray-700";
    case "error":
    case "failed":
      return "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-900/30 dark:text-rose-200 dark:ring-rose-800";
    default:
      return "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/30 dark:text-amber-200 dark:ring-amber-800";
  }
};

const scoreBarClassName = (score: number) => {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 60) return "bg-blue-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-rose-500";
};

const summarizeRoutes = (items: LeadRecordResponse[]) =>
  items.reduce<Record<string, number>>((acc, lead) => {
    const key = lead.recommended_route || "manual_review";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

const parseBatchRows = (source: string) => {
  const trimmed = source.trim();
  if (!trimmed) return [] as Array<Record<string, unknown>>;

  if (trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) {
      throw new Error("JSON import must be an array of row objects.");
    }
    return parsed as Array<Record<string, unknown>>;
  }

  if (trimmed.startsWith("{")) {
    return trimmed
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
  }

  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];

  const recognizedHeaders = new Set([
    "ip",
    "hostname",
    "domain",
    "port",
    "protocol",
    "service",
    "timestamp_seen",
  ]);

  const firstCells = lines[0]
    .split(",")
    .map((cell) => cell.trim().toLowerCase());
  const hasHeader = firstCells.some((cell) => recognizedHeaders.has(cell));
  const headers = hasHeader
    ? firstCells
    : [
        "ip",
        "hostname",
        "domain",
        "port",
        "protocol",
        "service",
        "timestamp_seen",
      ];
  const dataLines = hasHeader ? lines.slice(1) : lines;

  return dataLines
    .map((line) => line.split(",").map((cell) => cell.trim()))
    .filter((cells) => cells.some(Boolean))
    .map((cells) => {
      const row: Record<string, unknown> = {};
      headers.forEach((header, index) => {
        const value = cells[index];
        if (!header || !value) return;
        row[header] = header === "port" ? Number(value) : value;
      });
      return row;
    });
};

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-blue-50 p-3 text-blue-600 dark:bg-blue-900/30 dark:text-blue-200">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
            {label}
          </div>
          <div className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
            {value}
          </div>
          <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {detail}
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4 dark:border-gray-700">
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {description}
            </p>
          ) : null}
        </div>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function Leads() {
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState(() => getStoredAdminApiKey());
  const [adminKey, setAdminKey] = useState(() => getStoredAdminApiKey());
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "all">("all");
  const [minimumConfidence, setMinimumConfidence] = useState("0");
  const [page, setPage] = useState(1);
  const [manualForm, setManualForm] = useState({
    ip: "",
    hostname: "",
    domain: "",
    port: "443",
    protocol: "tcp",
    service: "https",
  });
  const [batchInput, setBatchInput] = useState(
    "ip,domain,port,protocol,service\n203.0.113.10,example.org,443,tcp,https",
  );
  const [isSubmittingManual, setIsSubmittingManual] = useState(false);
  const [isSubmittingBatch, setIsSubmittingBatch] = useState(false);
  const [isRunningAction, setIsRunningAction] = useState<
    | "enrich"
    | "resolve"
    | "rescore"
    | "reviewed"
    | "approved"
    | "suppressed"
    | null
  >(null);

  const {
    data: sessionData,
    isLoading: sessionLoading,
    isError: sessionError,
    error: sessionErrorValue,
    refetch: refetchSession,
  } = useQuery(
    ["lead-admin-session", adminKey],
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

  const {
    data: leadPage,
    isLoading: leadsLoading,
    isFetching: leadsFetching,
    refetch: refetchLeads,
  } = useQuery(
    ["lead-records", page, statusFilter, minimumConfidence],
    async () => {
      const response = await axios.get("/api/lead-records", {
        params: {
          page,
          size: 20,
          status: statusFilter === "all" ? undefined : statusFilter,
          minimum_confidence: minimumConfidence.trim()
            ? Number(minimumConfidence)
            : undefined,
        },
      });
      return response.data as PaginatedLeadRecordResponse;
    },
    {
      enabled: isAuthorized,
      keepPreviousData: true,
      refetchOnWindowFocus: false,
    },
  );

  const {
    data: selectedLead,
    isLoading: leadDetailLoading,
    isFetching: leadDetailFetching,
    refetch: refetchLeadDetail,
  } = useQuery(
    ["lead-record", selectedLeadId],
    async () => {
      const response = await axios.get(`/api/lead-records/${selectedLeadId}`);
      return response.data as LeadRecordResponse;
    },
    {
      enabled: isAuthorized && Boolean(selectedLeadId),
      refetchOnWindowFocus: false,
    },
  );

  const { data: clusters, refetch: refetchClusters } = useQuery(
    ["lead-clusters"],
    async () => {
      const response = await axios.get("/api/clusters");
      return response.data as CampaignClusterResponse[];
    },
    {
      enabled: isAuthorized,
      refetchOnWindowFocus: false,
    },
  );

  const { data: enrichmentRun, refetch: refetchEnrichmentRun } = useQuery(
    ["enrichment-run", selectedLead?.asset?.id],
    async () => {
      if (!selectedLead?.asset?.id) return null;
      try {
        const response = await axios.get(
          `/api/enrichment-runs/${selectedLead.asset.id}`,
        );
        return response.data as EnrichmentRunResponse;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          return null;
        }
        throw error;
      }
    },
    {
      enabled: isAuthorized && Boolean(selectedLead?.asset?.id),
      refetchOnWindowFocus: false,
    },
  );

  useEffect(() => {
    const firstLeadId = leadPage?.items?.[0]?.id;
    if (!selectedLeadId && firstLeadId) {
      setSelectedLeadId(firstLeadId);
      return;
    }
    if (
      selectedLeadId &&
      leadPage &&
      leadPage.items.length > 0 &&
      !leadPage.items.some((lead) => lead.id === selectedLeadId)
    ) {
      setSelectedLeadId(leadPage.items[0].id);
    }
  }, [leadPage, selectedLeadId]);

  const handleUnlock = async () => {
    const nextKey = apiKeyDraft.trim();
    if (!nextKey) {
      setMessage({
        type: "error",
        text: "Enter the shared admin API key to open the lead desk.",
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

  const refreshAll = async () => {
    await Promise.all([
      refetchLeads(),
      refetchLeadDetail(),
      refetchClusters(),
      refetchEnrichmentRun(),
    ]);
  };

  const handleManualCreate = async () => {
    setIsSubmittingManual(true);
    setMessage(null);
    try {
      const payload = {
        ip: manualForm.ip.trim() || undefined,
        hostname: manualForm.hostname.trim() || undefined,
        domain: manualForm.domain.trim() || undefined,
        port: parseNumber(manualForm.port),
        protocol: manualForm.protocol.trim() || undefined,
        service: manualForm.service.trim() || undefined,
      };
      const response = await axios.post("/api/assets/manual", payload);
      const lead = response.data as LeadRecordResponse;
      setSelectedLeadId(lead.id);
      setMessage({
        type: "success",
        text: `Created lead ${assetLabel(lead)}.`,
      });
      await refreshAll();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Manual lead creation failed: ${getErrorMessage(error)}`,
      });
    } finally {
      setIsSubmittingManual(false);
    }
  };

  const handleBatchImport = async () => {
    setIsSubmittingBatch(true);
    setMessage(null);
    try {
      const rows = parseBatchRows(batchInput);
      if (!rows.length) {
        throw new Error("Provide at least one batch row to import.");
      }
      const response = await axios.post("/api/assets/import", {
        source: "import",
        import_batch_id: `ui-${Date.now()}`,
        rows,
      });
      const payload = response.data as AssetImportResponse;
      if (payload.lead_record_ids[0]) {
        setSelectedLeadId(payload.lead_record_ids[0]);
      }
      setMessage({
        type: "success",
        text: `Imported ${payload.imported_count} rows (${payload.created_count} new, ${payload.updated_count} updated).`,
      });
      await refreshAll();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Batch import failed: ${getErrorMessage(error)}`,
      });
    } finally {
      setIsSubmittingBatch(false);
    }
  };

  const runLeadAction = async (
    action:
      | "enrich"
      | "resolve"
      | "rescore"
      | "reviewed"
      | "approved"
      | "suppressed",
  ) => {
    if (!selectedLead) return;
    setIsRunningAction(action);
    setMessage(null);
    try {
      if (action === "enrich") {
        const candidateDomains = Array.from(
          new Set(
            [
              selectedLead.asset?.domain,
              selectedLead.asset?.hostname,
              selectedLead.primary_contact?.source_url
                ? new URL(selectedLead.primary_contact.source_url).hostname
                : null,
            ].filter((value): value is string => Boolean(value)),
          ),
        );
        const response = await axios.post<JobQueuedResponse>(
          `/api/enrich/${selectedLead.asset_id}`,
          {
            requested_sources: ["rdap", "ptr", "security_txt", "website"],
            candidate_domains: candidateDomains,
            fetch_versions: {
              rdap: "v1",
              security_txt: "rfc9116-v1",
              website: "website-contact-v1",
            },
          },
        );
        setMessage({
          type: "success",
          text: `Enrichment ${response.data.status} (${response.data.job_type}).`,
        });
      }

      if (action === "resolve") {
        const response = await axios.post<JobQueuedResponse>(
          `/api/resolve/${selectedLead.id}`,
          {
            resolver_version: "resolver-v0.2",
            scorer_version: "score-v0.2",
            recompute_org_candidates: true,
            recompute_contact_routes: true,
          },
        );
        setMessage({
          type: "success",
          text: `Resolution ${response.data.status}.`,
        });
      }

      if (action === "rescore") {
        const response = await axios.post<JobQueuedResponse>(
          `/api/re-score/${selectedLead.id}`,
          {
            scorer_version: "score-v0.2",
            reason: "ui-rescore",
          },
        );
        setMessage({
          type: "success",
          text: `Re-score ${response.data.status}.`,
        });
      }

      if (["reviewed", "approved", "suppressed"].includes(action)) {
        await axios.post(`/api/lead-records/${selectedLead.id}/status`, {
          status: action,
        });
        setMessage({
          type: "success",
          text: `Lead marked ${action}.`,
        });
      }

      await refreshAll();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Action failed: ${getErrorMessage(error)}`,
      });
    } finally {
      setIsRunningAction(null);
    }
  };

  const routeSummary = useMemo(
    () => summarizeRoutes(leadPage?.items || []),
    [leadPage?.items],
  );

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

  return (
    <div className="space-y-6 px-4 sm:px-0">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-200">
            <Shield className="h-3.5 w-3.5" />
            Contact resolution and outreach prep
          </div>
          <h1 className="mt-3 text-3xl font-bold text-gray-900 dark:text-white">
            Lead Desk
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-gray-500 dark:text-gray-400">
            Turn exposed services into ranked, provenance-backed outreach leads
            using RDAP, PTR, security.txt, and public contact pages.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void refreshAll()}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
          >
            <RefreshCw
              className={`h-4 w-4 ${leadsFetching || leadDetailFetching ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
          <button
            type="button"
            onClick={handleLock}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
          >
            <ShieldAlert className="h-4 w-4" />
            Lock
          </button>
        </div>
      </div>

      {message ? (
        <div
          className={`flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm ${
            message.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200"
              : "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-200"
          }`}
        >
          {message.type === "success" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4" />
          ) : (
            <AlertCircle className="mt-0.5 h-4 w-4" />
          )}
          <span>{message.text}</span>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-4">
        <MetricCard
          label="Queue"
          value={numberFormatter.format(leadPage?.total || 0)}
          detail={`${numberFormatter.format(leadPage?.items.length || 0)} visible on this page`}
          icon={FileSearch}
        />
        <MetricCard
          label="Approved"
          value={numberFormatter.format(
            (leadPage?.items || []).filter((item) => item.status === "approved")
              .length,
          )}
          detail="Current page approved for outreach"
          icon={Target}
        />
        <MetricCard
          label="security.txt routes"
          value={numberFormatter.format(routeSummary.security_txt || 0)}
          detail="Current page leads with the strongest route"
          icon={Shield}
        />
        <MetricCard
          label="Campaigns"
          value={numberFormatter.format(clusters?.length || 0)}
          detail="Active outreach clusters"
          icon={Briefcase}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[360px,minmax(0,1fr),340px]">
        <div className="space-y-6">
          <SectionCard
            title="Intake"
            description="Seed the queue from a one-off asset or a quick batch import."
          >
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                  <Plus className="h-4 w-4" />
                  Manual asset
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <input
                    className={inputClassName}
                    placeholder="IP"
                    value={manualForm.ip}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        ip: event.target.value,
                      }))
                    }
                  />
                  <input
                    className={inputClassName}
                    placeholder="Hostname"
                    value={manualForm.hostname}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        hostname: event.target.value,
                      }))
                    }
                  />
                  <input
                    className={inputClassName}
                    placeholder="Domain"
                    value={manualForm.domain}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        domain: event.target.value,
                      }))
                    }
                  />
                  <input
                    className={inputClassName}
                    placeholder="Port"
                    value={manualForm.port}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        port: event.target.value,
                      }))
                    }
                  />
                  <input
                    className={inputClassName}
                    placeholder="Protocol"
                    value={manualForm.protocol}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        protocol: event.target.value,
                      }))
                    }
                  />
                  <input
                    className={inputClassName}
                    placeholder="Service"
                    value={manualForm.service}
                    onChange={(event) =>
                      setManualForm((current) => ({
                        ...current,
                        service: event.target.value,
                      }))
                    }
                  />
                </div>
                <button
                  type="button"
                  onClick={() => void handleManualCreate()}
                  disabled={isSubmittingManual}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSubmittingManual ? (
                    <Loader className="h-4 w-4 animate-spin" />
                  ) : (
                    <Plus className="h-4 w-4" />
                  )}
                  Create lead
                </button>
              </div>

              <div className="space-y-3 border-t border-gray-200 pt-5 dark:border-gray-700">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                  <Upload className="h-4 w-4" />
                  Quick batch import
                </div>
                <textarea
                  className={textareaClassName}
                  value={batchInput}
                  onChange={(event) => setBatchInput(event.target.value)}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Accepts JSON array, JSON lines, or simple CSV with headers.
                </p>
                <button
                  type="button"
                  onClick={() => void handleBatchImport()}
                  disabled={isSubmittingBatch}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
                >
                  {isSubmittingBatch ? (
                    <Loader className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  Import rows
                </button>
              </div>
            </div>
          </SectionCard>

          <SectionCard
            title="Queue"
            description="Review scored leads and select one for detail."
            action={
              <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                <Search className="h-3.5 w-3.5" />
                {leadPage
                  ? `${leadPage.page} / ${Math.max(leadPage.pages, 1)}`
                  : "—"}
              </div>
            }
          >
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <select
                  className={inputClassName}
                  value={statusFilter}
                  onChange={(event) => {
                    setPage(1);
                    setStatusFilter(event.target.value as LeadStatus | "all");
                  }}
                >
                  <option value="all">All statuses</option>
                  <option value="new">New</option>
                  <option value="reviewed">Reviewed</option>
                  <option value="approved">Approved</option>
                  <option value="suppressed">Suppressed</option>
                  <option value="exported">Exported</option>
                </select>
                <input
                  className={inputClassName}
                  value={minimumConfidence}
                  onChange={(event) => {
                    setPage(1);
                    setMinimumConfidence(event.target.value);
                  }}
                  placeholder="Min confidence"
                />
              </div>

              {leadsLoading ? (
                <div className="flex items-center justify-center py-12 text-gray-500 dark:text-gray-400">
                  <Loader className="h-5 w-5 animate-spin" />
                </div>
              ) : leadPage?.items.length ? (
                <div className="space-y-3">
                  {leadPage.items.map((lead) => {
                    const isSelected = lead.id === selectedLeadId;
                    return (
                      <button
                        key={lead.id}
                        type="button"
                        onClick={() => setSelectedLeadId(lead.id)}
                        className={`w-full rounded-xl border px-4 py-3 text-left transition-colors ${
                          isSelected
                            ? "border-blue-300 bg-blue-50 shadow-sm dark:border-blue-700 dark:bg-blue-900/20"
                            : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900/20 dark:hover:bg-gray-800/60"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-gray-900 dark:text-white">
                              {assetLabel(lead)}
                            </div>
                            <div className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400">
                              {lead.organization?.org_candidates?.[0]?.name ||
                                lead.primary_contact?.value ||
                                routeLabel(lead.recommended_route)}
                            </div>
                          </div>
                          <span
                            className={`inline-flex rounded-full px-2 py-1 text-[11px] font-medium ring-1 ${statusClassName(
                              lead.status,
                            )}`}
                          >
                            {lead.status}
                          </span>
                        </div>
                        <div className="mt-3 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                          <span>{routeLabel(lead.recommended_route)}</span>
                          <span>•</span>
                          <span>{formatRelative(lead.updated_at)}</span>
                        </div>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                          <div
                            className={`h-full ${scoreBarClassName(
                              lead.scores.confidence_score,
                            )}`}
                            style={{
                              width: `${Math.max(
                                4,
                                Math.min(100, lead.scores.confidence_score),
                              )}%`,
                            }}
                          />
                        </div>
                        <div className="mt-2 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                          <span>
                            Confidence{" "}
                            {Math.round(lead.scores.confidence_score)}
                          </span>
                          <span>
                            Route {Math.round(lead.scores.route_legitimacy)}
                          </span>
                        </div>
                      </button>
                    );
                  })}

                  <div className="flex items-center justify-between gap-3 border-t border-gray-200 pt-3 text-sm dark:border-gray-700">
                    <button
                      type="button"
                      disabled={page <= 1}
                      onClick={() =>
                        setPage((current) => Math.max(1, current - 1))
                      }
                      className="rounded-lg border border-gray-300 px-3 py-2 text-gray-700 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200"
                    >
                      Previous
                    </button>
                    <span className="text-gray-500 dark:text-gray-400">
                      Page {leadPage?.page || 1} of{" "}
                      {Math.max(leadPage?.pages || 1, 1)}
                    </span>
                    <button
                      type="button"
                      disabled={Boolean(leadPage && page >= leadPage.pages)}
                      onClick={() => setPage((current) => current + 1)}
                      className="rounded-lg border border-gray-300 px-3 py-2 text-gray-700 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200"
                    >
                      Next
                    </button>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-gray-300 px-4 py-10 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                  No leads match the current filter.
                </div>
              )}
            </div>
          </SectionCard>
        </div>

        <div className="space-y-6">
          <SectionCard
            title="Lead Detail"
            description="Inspect provenance, route quality, and update workflow state."
            action={
              selectedLead ? (
                <span
                  className={`inline-flex rounded-full px-2 py-1 text-[11px] font-medium ring-1 ${statusClassName(
                    selectedLead.status,
                  )}`}
                >
                  {selectedLead.status}
                </span>
              ) : null
            }
          >
            {leadDetailLoading && !selectedLead ? (
              <div className="flex items-center justify-center py-12 text-gray-500 dark:text-gray-400">
                <Loader className="h-5 w-5 animate-spin" />
              </div>
            ) : selectedLead ? (
              <div className="space-y-6">
                <div className="flex flex-col gap-4 rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
                        {assetLabel(selectedLead)}
                      </h3>
                      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                        Updated {formatRelative(selectedLead.updated_at)} •
                        route {routeLabel(selectedLead.recommended_route)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void runLeadAction("enrich")}
                        disabled={isRunningAction !== null}
                        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                      >
                        {isRunningAction === "enrich" ? (
                          <Loader className="h-4 w-4 animate-spin" />
                        ) : (
                          <Sparkles className="h-4 w-4" />
                        )}
                        Enrich
                      </button>
                      <button
                        type="button"
                        onClick={() => void runLeadAction("resolve")}
                        disabled={isRunningAction !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                      >
                        {isRunningAction === "resolve" ? (
                          <Loader className="h-4 w-4 animate-spin" />
                        ) : (
                          <Building2 className="h-4 w-4" />
                        )}
                        Resolve
                      </button>
                      <button
                        type="button"
                        onClick={() => void runLeadAction("rescore")}
                        disabled={isRunningAction !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                      >
                        {isRunningAction === "rescore" ? (
                          <Loader className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                        Re-score
                      </button>
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-4">
                    <div className="rounded-xl bg-white p-3 shadow-sm dark:bg-gray-800">
                      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Confidence
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
                        {Math.round(selectedLead.scores.confidence_score)}
                      </div>
                    </div>
                    <div className="rounded-xl bg-white p-3 shadow-sm dark:bg-gray-800">
                      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Org confidence
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
                        {Math.round(selectedLead.scores.org_confidence)}
                      </div>
                    </div>
                    <div className="rounded-xl bg-white p-3 shadow-sm dark:bg-gray-800">
                      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Contact quality
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
                        {Math.round(selectedLead.scores.contact_quality)}
                      </div>
                    </div>
                    <div className="rounded-xl bg-white p-3 shadow-sm dark:bg-gray-800">
                      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        Route legitimacy
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
                        {Math.round(selectedLead.scores.route_legitimacy)}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void runLeadAction("reviewed")}
                      disabled={isRunningAction !== null}
                      className="rounded-lg bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-60 dark:bg-blue-900/30 dark:text-blue-200"
                    >
                      Mark reviewed
                    </button>
                    <button
                      type="button"
                      onClick={() => void runLeadAction("approved")}
                      disabled={isRunningAction !== null}
                      className="rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60 dark:bg-emerald-900/30 dark:text-emerald-200"
                    >
                      Approve outreach
                    </button>
                    <button
                      type="button"
                      onClick={() => void runLeadAction("suppressed")}
                      disabled={isRunningAction !== null}
                      className="rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-60 dark:bg-gray-800 dark:text-gray-200"
                    >
                      Suppress
                    </button>
                  </div>
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
                    <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                      <Building2 className="h-4 w-4" />
                      Organization resolution
                    </div>
                    <div className="mt-3 space-y-3">
                      <div>
                        <div className="text-sm font-semibold text-gray-900 dark:text-white">
                          {selectedLead.organization?.org_candidates?.[0]
                            ?.name ||
                            selectedLead.organization?.reviewer_note ||
                            "No resolved organization yet"}
                        </div>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          Mode{" "}
                          {selectedLead.organization?.resolution_mode || "auto"}{" "}
                          • resolved{" "}
                          {formatRelative(
                            selectedLead.organization?.resolved_at,
                          )}
                        </div>
                      </div>
                      <div className="space-y-2">
                        {(selectedLead.organization?.org_candidates || []).map(
                          (candidate) => (
                            <div
                              key={candidate.id}
                              className="rounded-xl bg-gray-50 px-3 py-2 text-sm dark:bg-gray-900/50"
                            >
                              <div className="flex items-center justify-between gap-3">
                                <span className="font-medium text-gray-900 dark:text-white">
                                  {candidate.name}
                                </span>
                                <span className="text-xs text-gray-500 dark:text-gray-400">
                                  {Math.round(candidate.score)}
                                </span>
                              </div>
                              {candidate.org_conflict_penalty > 0 ? (
                                <div className="mt-1 text-xs text-rose-600 dark:text-rose-300">
                                  conflict penalty{" "}
                                  {Math.round(candidate.org_conflict_penalty)}
                                </div>
                              ) : null}
                            </div>
                          ),
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
                    <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                      <Mail className="h-4 w-4" />
                      Contact routes
                    </div>
                    <div className="mt-3 space-y-3">
                      {selectedLead.contact_candidates.length ? (
                        selectedLead.contact_candidates.map((candidate) => (
                          <div
                            key={candidate.id}
                            className="rounded-xl bg-gray-50 px-3 py-3 dark:bg-gray-900/50"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <div className="text-sm font-medium text-gray-900 dark:text-white">
                                  #{candidate.rank}{" "}
                                  {routeLabel(candidate.route)}
                                </div>
                                <div className="mt-1 break-all text-xs text-gray-500 dark:text-gray-400">
                                  {candidate.contact?.value ||
                                    "No contact payload"}
                                </div>
                              </div>
                              <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                                {Math.round(candidate.score)}
                              </span>
                            </div>
                            <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-500 dark:text-gray-400">
                              <div>
                                org {Math.round(candidate.org_confidence)}
                              </div>
                              <div>
                                contact {Math.round(candidate.contact_quality)}
                              </div>
                              <div>
                                route {Math.round(candidate.route_legitimacy)}
                              </div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                          No ranked contacts yet. Run enrich and resolve.
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                    <CircleDot className="h-4 w-4" />
                    Evidence
                  </div>
                  <div className="mt-3 space-y-3">
                    {selectedLead.evidence_steps.length ? (
                      selectedLead.evidence_steps.map((step) => (
                        <div
                          key={step.id}
                          className="rounded-xl bg-gray-50 px-4 py-3 dark:bg-gray-900/50"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-medium text-gray-900 dark:text-white">
                                {step.kind.replace(/_/g, " ")}
                              </div>
                              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                {step.source_type} •{" "}
                                {formatTimestamp(step.observed_at)}
                              </div>
                            </div>
                            <div className="text-xs text-gray-500 dark:text-gray-400">
                              weight {Math.round(step.weight)} • confidence{" "}
                              {Math.round(step.confidence)}
                            </div>
                          </div>
                          {step.normalized_value ? (
                            <div className="mt-3 break-all rounded-lg bg-white px-3 py-2 text-sm text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                              {step.normalized_value}
                            </div>
                          ) : null}
                          {step.source_url ? (
                            <a
                              href={step.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-3 inline-flex text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
                            >
                              {step.source_url}
                            </a>
                          ) : null}
                        </div>
                      ))
                    ) : (
                      <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                        No evidence has been recorded for this lead yet.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-gray-300 px-4 py-14 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                Select a lead from the queue to inspect it.
              </div>
            )}
          </SectionCard>
        </div>

        <div className="space-y-6">
          <SectionCard
            title="Enrichment Status"
            description="Per-source fetch state for the selected asset."
          >
            {selectedLead?.asset?.id ? (
              enrichmentRun ? (
                <div className="space-y-3">
                  {[
                    ["RDAP", enrichmentRun.rdap_status],
                    ["PTR", enrichmentRun.ptr_status],
                    ["TLS / CT", enrichmentRun.tls_ct_status],
                    ["security.txt", enrichmentRun.security_txt_status],
                    ["Contact pages", enrichmentRun.contact_page_status],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-900/50"
                    >
                      <span className="text-sm text-gray-700 dark:text-gray-200">
                        {label}
                      </span>
                      <span
                        className={`inline-flex rounded-full px-2 py-1 text-[11px] font-medium ring-1 ${statusClassName(
                          value,
                        )}`}
                      >
                        {value}
                      </span>
                    </div>
                  ))}
                  <div className="rounded-xl border border-gray-200 px-3 py-3 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
                    Last started {formatRelative(enrichmentRun.last_started_at)}{" "}
                    • last finished{" "}
                    {formatRelative(enrichmentRun.last_finished_at)}
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                  No enrichment run has been recorded for this asset yet.
                </div>
              )
            ) : (
              <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                Select a lead to inspect run status.
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Campaigns"
            description="Clustered outreach targets by ASN, region, or org density."
          >
            {clusters?.length ? (
              <div className="space-y-3">
                {clusters.map((cluster) => (
                  <div
                    key={cluster.id}
                    className="rounded-xl border border-gray-200 px-4 py-3 dark:border-gray-700"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {cluster.cluster_key}
                        </div>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          {cluster.cluster_type}
                          {cluster.geo_region ? ` • ${cluster.geo_region}` : ""}
                        </div>
                      </div>
                      <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                        {numberFormatter.format(cluster.lead_count)} leads
                      </span>
                    </div>
                    {cluster.org_density != null ? (
                      <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                        density {Math.round(cluster.org_density)}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
                No campaign clusters yet. Create them after the queue has
                meaningful density.
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Why this works"
            description="Current page route mix, useful for triage."
          >
            <div className="space-y-3 text-sm text-gray-600 dark:text-gray-300">
              {Object.entries(routeSummary).length ? (
                Object.entries(routeSummary)
                  .sort((a, b) => b[1] - a[1])
                  .map(([route, count]) => (
                    <div
                      key={route}
                      className="flex items-center justify-between rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-900/50"
                    >
                      <span>{routeLabel(route as RecommendedRoute)}</span>
                      <span className="font-medium text-gray-900 dark:text-white">
                        {numberFormatter.format(count)}
                      </span>
                    </div>
                  ))
              ) : (
                <div className="rounded-xl border border-dashed border-gray-300 px-4 py-6 text-gray-500 dark:border-gray-600 dark:text-gray-400">
                  No route distribution yet.
                </div>
              )}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
