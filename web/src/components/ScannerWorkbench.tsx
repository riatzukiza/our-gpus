import { useEffect, useState } from "react";
import { useQuery } from "react-query";
import axios from "axios";
import {
  AlertCircle,
  CheckCircle,
  Loader,
  Radar,
  Search,
  Settings2,
  Square,
} from "lucide-react";

type SchedulerStatus =
  | "running"
  | "stopping"
  | "stopped"
  | "not_running"
  | "initializing";

interface ScannerConfigResponse {
  aco: {
    port: string;
    rate: number;
    max_block_duration_s: number;
    min_scan_interval_s: number;
    breathing_room_s: number;
    router_mac: string;
    interface: string;
    exclude_file: string;
    aco_alpha: number;
    aco_beta: number;
    aco_decay: number;
    aco_reinforcement: number;
    aco_penalty: number;
  };
  tor: {
    max_hosts: number;
    concurrency: number;
  };
  shodan: {
    api_key_configured: boolean;
    base_query: string;
    page_limit: number;
    max_matches: number;
    max_queries: number;
    query_max_length: number;
  };
  scan: {
    target: string;
    port: string;
    rate: number;
    router_mac: string;
    strategy: string;
  };
}

interface QueryPlanResponse {
  query_count: number;
  queries: string[];
  total_excludes: number;
  applied_excludes: number;
  omitted_excludes: number;
  max_query_length: number;
}

interface WorkbenchMessage {
  type: "success" | "error";
  text: string;
}

interface ScannerWorkbenchProps {
  schedulerStatus: SchedulerStatus;
  onRefresh: () => Promise<unknown>;
}

const inputClassName =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white";

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

const normalizeStrategy = (strategy: string) =>
  strategy === "tor" ? "tor-connect" : strategy;

export default function ScannerWorkbench({
  schedulerStatus,
  onRefresh,
}: ScannerWorkbenchProps) {
  const [message, setMessage] = useState<WorkbenchMessage | null>(null);
  const [plan, setPlan] = useState<QueryPlanResponse | null>(null);
  const [runningAction, setRunningAction] = useState<
    "continuous-start" | "continuous-stop" | "single-run" | "query-plan" | null
  >(null);
  const [initialized, setInitialized] = useState(false);

  const [form, setForm] = useState({
    strategy: "tor-connect",
    target: "0.0.0.0/0",
    port: "11434",
    rate: "100000",
    routerMac: "00:21:59:a0:cf:c1",
    torMaxHosts: "4096",
    torConcurrency: "32",
    shodanQuery: "",
    shodanPageLimit: "3",
    shodanMaxMatches: "1000",
    shodanMaxQueries: "24",
    shodanQueryMaxLength: "900",
    maxBlockDurationS: "120",
    minScanIntervalS: "3600",
    breathingRoomS: "2",
    interface: "eth0",
    alpha: "0.6",
    beta: "0.4",
    decay: "0.05",
    reinforcement: "0.3",
    penalty: "0.2",
  });

  const { data, isLoading } = useQuery(
    ["admin-scanner-config"],
    async () => {
      const response = await axios.get("/api/admin/scanner/config");
      return response.data as ScannerConfigResponse;
    },
    {
      refetchOnWindowFocus: false,
    },
  );

  useEffect(() => {
    if (!data || initialized) {
      return;
    }

    setForm({
      strategy: normalizeStrategy(data.scan.strategy),
      target: data.scan.target,
      port: data.scan.port,
      rate: String(data.scan.rate),
      routerMac: data.scan.router_mac,
      torMaxHosts: String(data.tor.max_hosts),
      torConcurrency: String(data.tor.concurrency),
      shodanQuery: data.shodan.base_query,
      shodanPageLimit: String(data.shodan.page_limit),
      shodanMaxMatches: String(data.shodan.max_matches),
      shodanMaxQueries: String(data.shodan.max_queries),
      shodanQueryMaxLength: String(data.shodan.query_max_length),
      maxBlockDurationS: String(data.aco.max_block_duration_s),
      minScanIntervalS: String(data.aco.min_scan_interval_s),
      breathingRoomS: String(data.aco.breathing_room_s),
      interface: data.aco.interface,
      alpha: String(data.aco.aco_alpha),
      beta: String(data.aco.aco_beta),
      decay: String(data.aco.aco_decay),
      reinforcement: String(data.aco.aco_reinforcement),
      penalty: String(data.aco.aco_penalty),
    });
    setInitialized(true);
  }, [data, initialized]);

  const updateField = (key: keyof typeof form, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleStartContinuous = async () => {
    setRunningAction("continuous-start");
    setMessage(null);
    try {
      await axios.post("/api/aco/scan/start", {
        strategy: form.strategy,
        port: form.port.trim(),
        rate: Number(form.rate),
        max_block_duration_s: Number(form.maxBlockDurationS),
        min_scan_interval_s: Number(form.minScanIntervalS),
        breathing_room_s: Number(form.breathingRoomS),
        router_mac: form.routerMac.trim(),
        interface: form.interface.trim(),
        tor_max_hosts: Number(form.torMaxHosts),
        tor_concurrency: Number(form.torConcurrency),
        aco_alpha: Number(form.alpha),
        aco_beta: Number(form.beta),
        aco_decay: Number(form.decay),
        aco_reinforcement: Number(form.reinforcement),
        aco_penalty: Number(form.penalty),
      });
      setMessage({ type: "success", text: "Continuous ACO workflow started." });
      await onRefresh();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Failed to start continuous workflow: ${getErrorMessage(error)}`,
      });
    } finally {
      setRunningAction(null);
    }
  };

  const handleStopContinuous = async () => {
    setRunningAction("continuous-stop");
    setMessage(null);
    try {
      await axios.post("/api/aco/scan/stop");
      setMessage({
        type: "success",
        text: "Continuous ACO workflow stop requested.",
      });
      await onRefresh();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Failed to stop continuous workflow: ${getErrorMessage(error)}`,
      });
    } finally {
      setRunningAction(null);
    }
  };

  const handleRunSingle = async () => {
    setRunningAction("single-run");
    setMessage(null);
    try {
      const response = await axios.post("/api/admin/scanner/run", {
        strategy: form.strategy,
        target: form.target.trim(),
        port: form.port.trim(),
        rate: Number(form.rate),
        router_mac: form.routerMac.trim(),
        tor_max_hosts: Number(form.torMaxHosts),
        tor_concurrency: Number(form.torConcurrency),
        shodan_query: form.shodanQuery.trim() || null,
        shodan_page_limit: Number(form.shodanPageLimit),
        shodan_max_matches: Number(form.shodanMaxMatches),
        shodan_max_queries: Number(form.shodanMaxQueries),
        shodan_query_max_length: Number(form.shodanQueryMaxLength),
      });
      setMessage({
        type: "success",
        text: `Started one-off ${normalizeStrategy(response.data.strategy)} workflow ${response.data.scan_id}.`,
      });
      await onRefresh();
    } catch (error) {
      setMessage({
        type: "error",
        text: `Failed to start one-off workflow: ${getErrorMessage(error)}`,
      });
    } finally {
      setRunningAction(null);
    }
  };

  const handleBuildPlan = async () => {
    setRunningAction("query-plan");
    setMessage(null);
    try {
      const response = await axios.post("/api/admin/scanner/query-plan", {
        target: form.target.trim(),
        port: form.port.trim(),
        base_query: form.shodanQuery.trim(),
        max_query_length: Number(form.shodanQueryMaxLength),
        max_queries: Number(form.shodanMaxQueries),
      });
      setPlan(response.data as QueryPlanResponse);
    } catch (error) {
      setMessage({
        type: "error",
        text: `Failed to build Shodan plan: ${getErrorMessage(error)}`,
      });
    } finally {
      setRunningAction(null);
    }
  };

  if (isLoading || !data) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center justify-center py-8">
          <Loader className="h-6 w-6 animate-spin text-blue-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-start gap-3">
        <Settings2 className="mt-1 h-5 w-5 text-blue-600 dark:text-blue-300" />
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Workflow Config
          </h3>
          <p className="mt-1 max-w-4xl text-sm text-gray-500 dark:text-gray-400">
            Every button below reads from this same config. Use{" "}
            <strong>Start Continuous ACO Workflow</strong> for the long-running
            block scheduler. Use <strong>Run One-off Workflow</strong> for a
            single ad-hoc discovery run. Tor Connect is the default safe path.
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 2xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.75fr)]">
        <div className="space-y-6">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <label className="text-sm text-gray-600 dark:text-gray-300">
              <span className="mb-1 block">Discovery strategy</span>
              <select
                value={form.strategy}
                onChange={(event) =>
                  updateField("strategy", event.target.value)
                }
                className={inputClassName}
              >
                <option value="tor-connect">tor-connect</option>
                <option value="shodan">shodan</option>
                <option value="masscan">masscan</option>
              </select>
            </label>
            <label className="text-sm text-gray-600 dark:text-gray-300">
              <span className="mb-1 block">Target</span>
              <input
                value={form.target}
                onChange={(event) => updateField("target", event.target.value)}
                className={inputClassName}
              />
            </label>
            <label className="text-sm text-gray-600 dark:text-gray-300">
              <span className="mb-1 block">Port</span>
              <input
                value={form.port}
                onChange={(event) => updateField("port", event.target.value)}
                className={inputClassName}
              />
            </label>
            <label className="text-sm text-gray-600 dark:text-gray-300">
              <span className="mb-1 block">Rate</span>
              <input
                value={form.rate}
                onChange={(event) => updateField("rate", event.target.value)}
                className={inputClassName}
              />
            </label>
            <label className="text-sm text-gray-600 dark:text-gray-300 xl:col-span-2">
              <span className="mb-1 block">Router MAC</span>
              <input
                value={form.routerMac}
                onChange={(event) =>
                  updateField("routerMac", event.target.value)
                }
                className={inputClassName}
              />
            </label>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
              Continuous ACO tuning
            </h4>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {[
                ["maxBlockDurationS", "Max block duration (s)"],
                ["minScanIntervalS", "Min revisit interval (s)"],
                ["breathingRoomS", "Breathing room (s)"],
                ["interface", "Interface"],
                ["alpha", "ACO alpha"],
                ["beta", "ACO beta"],
                ["decay", "ACO decay"],
                ["reinforcement", "ACO reinforcement"],
                ["penalty", "ACO penalty"],
              ].map(([key, label]) => (
                <label
                  key={key}
                  className="text-sm text-gray-600 dark:text-gray-300"
                >
                  <span className="mb-1 block">{label}</span>
                  <input
                    value={form[key as keyof typeof form]}
                    onChange={(event) =>
                      updateField(key as keyof typeof form, event.target.value)
                    }
                    className={inputClassName}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
              Strategy-specific knobs
            </h4>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Tor max hosts</span>
                <input
                  value={form.torMaxHosts}
                  onChange={(event) =>
                    updateField("torMaxHosts", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Tor concurrency</span>
                <input
                  value={form.torConcurrency}
                  onChange={(event) =>
                    updateField("torConcurrency", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300 xl:col-span-3">
                <span className="mb-1 block">Shodan base query</span>
                <input
                  value={form.shodanQuery}
                  onChange={(event) =>
                    updateField("shodanQuery", event.target.value)
                  }
                  className={inputClassName}
                  placeholder="product:Ollama"
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Shodan page limit</span>
                <input
                  value={form.shodanPageLimit}
                  onChange={(event) =>
                    updateField("shodanPageLimit", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Shodan max matches</span>
                <input
                  value={form.shodanMaxMatches}
                  onChange={(event) =>
                    updateField("shodanMaxMatches", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Shodan max queries</span>
                <input
                  value={form.shodanMaxQueries}
                  onChange={(event) =>
                    updateField("shodanMaxQueries", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300">
                <span className="mb-1 block">Shodan query max length</span>
                <input
                  value={form.shodanQueryMaxLength}
                  onChange={(event) =>
                    updateField("shodanQueryMaxLength", event.target.value)
                  }
                  className={inputClassName}
                />
              </label>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              {data.shodan.api_key_configured ? (
                <CheckCircle className="h-4 w-4 text-emerald-500" />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber-500" />
              )}
              <span>
                {data.shodan.api_key_configured
                  ? "Shodan API key is configured."
                  : "No Shodan API key is configured in the backend env."}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={handleStartContinuous}
              disabled={
                runningAction !== null ||
                schedulerStatus === "running" ||
                schedulerStatus === "stopping" ||
                schedulerStatus === "initializing"
              }
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
            >
              {runningAction === "continuous-start" ? (
                <Loader className="h-4 w-4 animate-spin" />
              ) : (
                <Radar className="h-4 w-4" />
              )}
              Start Continuous ACO Workflow
            </button>
            <button
              type="button"
              onClick={handleStopContinuous}
              disabled={
                runningAction !== null ||
                (schedulerStatus !== "running" &&
                  schedulerStatus !== "stopping" &&
                  schedulerStatus !== "initializing")
              }
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-800 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {runningAction === "continuous-stop" ? (
                <Loader className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-4 w-4" />
              )}
              Stop Continuous Workflow
            </button>
            <button
              type="button"
              onClick={handleRunSingle}
              disabled={runningAction !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-400"
            >
              {runningAction === "single-run" ? (
                <Loader className="h-4 w-4 animate-spin" />
              ) : (
                <Radar className="h-4 w-4" />
              )}
              Run One-off Workflow
            </button>
            <button
              type="button"
              onClick={handleBuildPlan}
              disabled={runningAction !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              {runningAction === "query-plan" ? (
                <Loader className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Generate Shodan Query Plan
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-sm font-semibold text-gray-900 dark:text-white">
              How this maps to the workflow
            </p>
            <div className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">
              <p>
                <strong>Continuous ACO workflow</strong>: repeatedly chooses the
                next block and runs the scanning workflow in the background.
              </p>
              <p>
                <strong>One-off workflow</strong>: runs the same discovery stack
                once for the selected strategy and target.
              </p>
              <p>
                <strong>Strategy default</strong>: Tor Connect is preselected
                because it is the safest active path.
              </p>
            </div>
          </div>

          {plan && (
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40">
              <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                <span>{plan.query_count} queries</span>
                <span>
                  {plan.applied_excludes}/{plan.total_excludes} excludes applied
                </span>
                <span>{plan.omitted_excludes} omitted</span>
                <span>max length {plan.max_query_length}</span>
              </div>
              <div className="mt-3 max-h-[32rem] overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs text-slate-100">
                <pre className="whitespace-pre-wrap break-words">
                  {plan.queries.join("\n\n")}
                </pre>
              </div>
            </div>
          )}

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
        </div>
      </div>
    </div>
  );
}
