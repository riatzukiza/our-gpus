# Admin Page Layout

## Status
Draft — design phase

## Contract

The Admin page is the command center for Sintel operators. It presents a workflow-first view of the system, with evidence and provenance surfaces always visible.

## Layout Architecture

### Three-Pane Desktop Layout

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Header Bar                                                                 │
│ [Sintel] [Admin] [Leads] [Explore]              [User] [Lock] [Polling]   │
├─────────────────┬──────────────────────────────────┬──────────────────────┤
│ Surface 1       │ Surface 2-5 (Center)             │ Surface 6            │
│ Workflow Rail   │ World Map + Control Console     │ Evidence Ledger      │
│ (w-80, 320px)   │ + Groups + Jobs                 │ (w-[26rem], 416px)   │
│                 │                                  │                      │
│ [Workflows]     │ ┌────────────────────────────┐   │ ┌──────────────────┐ │
│ ┌─────────────┐ │ │ Overview KPIs              │   │ │ Evidence Ledger │ │
│ │ masscan //  │ │ ├────────────────────────────┤   │ │                  │ │
│ │ 192.0.2.0/24│ │ │ Control Console            │   │ │ Workflow: abc123│ │
│ │ RUNNING      │ │ │ (ScannerWorkbench)         │   │ │ Policy: sha...  │ │
│ └─────────────┘ │ ├────────────────────────────┤   │ │ Exclusions: sha │ │
│ ┌─────────────┐ │ │ Host Groups                │   │ │                  │ │
│ │ tor-connect │ │ ├────────────────────────────┤   │ │ Stage Receipts  │ │
│ │ 10.0.0.0/8  │ │ │ World Map                  │   │ │ ──────────────── │ │
│ │ COMPLETED   │ │ │ (ScannerWorldMap)          │   │ │ DISCOVER ✓     │ │
│ └─────────────┘ │ ├────────────────────────────┤   │ │ INGEST ✓        │ │
│ ┌─────────────┐ │ │ Current Workflow / Logs    │   │ │ VERIFY ⏳       │ │
│ │ shodan      │ │ ├────────────────────────────┤   │ │ GEOCODE ░       │ │
│ │ global      │ │ │ Probe Stats / Jobs Panel   │   │ │ ENRICH ░        │ │
│ │ BLOCKED     │ │ ├────────────────────────────┤   │ │                  │ │
│ └─────────────┘ │ │ Workflow History           │   │ │ Evidence        │ │
│                 │ └────────────────────────────┘   │ │ [discover.json] │ │
│                 │                                  │ │ [verify.json]   │ │
│                 │ (flexible, scrollable)            │ └──────────────────┘ │
│ (fixable left)  │                                  │ (fixable right)     │
└─────────────────┴──────────────────────────────────┴──────────────────────┘
```

### Responsive Behavior

| Screen | Left Rail | Center | Right Ledger |
|--------|-----------|--------|---------------|
| Desktop (≥1536px) | Visible, fixed | Full width | Visible, fixed |
| Desktop (1280-1535px) | Visible, fixed | Full width | Collapsed, tab |
| Tablet (768-1279px) | Collapsed, drawer | Full width | Collapsed, tab |
| Mobile (<768px) | Hidden | Full width | Hidden |

## Surface Responsibilities

### Surface 1: Workflow Rail

Purpose: Show all workflows, their statuses, and allow quick selection.

Must display:

- Workflow ID (shortened)
- Strategy (masscan, tor-connect, shodan)
- Target/port
- Current stage
- Status with color coding
- Last error or policy block reason

Selection behavior:

- Click workflow → populates Evidence Ledger
- Active workflow highlighted with accent border

### Surface 2: World Map

Purpose: Geographic theater view of discovered infrastructure.

Must display:

- Country aggregates
- Host points
- Block overlays
- Workflow-scoped filtering (toggle global vs. selected workflow)

### Surface 3: Control Console

Purpose: Configure and launch workflows.

Must include:

- Strategy selector (with risk tier badges)
- Target input + port
- Strategy-specific knobs
- Continuous scheduler controls
- Exclusion preview link
- Action buttons (Run, Stop, Schedule)

### Surface 4: Host Groups

Purpose: Show group-based context for discovered hosts.

Must display:

- Active groups
- Group membership counts
- Group-based actions

### Surface 5: Jobs / Status

Purpose: Show Celery worker health and job queue.

Must display:

- Worker status
- Recent jobs
- Queue depth
- Error counts

### Surface 6: Evidence Ledger

Purpose: Show provenance and stage receipts for selected workflow.

Must display:

- Workflow summary (strategy, target)
- Policy snapshot hash
- Exclusion snapshot hash
- Stage receipts with metrics
- Evidence references
- Raw log links

## Component Mapping

| Legacy Component | New Location |
|------------------|---------------|
| `AdminUnlockPanel` | Full-screen overlay (unchanged) |
| `OverviewGrid` | Strip in center pane |
| `ScannerWorkbench` | Control Console in center |
| `HostGroupsPanel` | Below Control Console |
| `ScannerWorldMap` | Center pane, after Groups |
| `CurrentWorkflowCard` | Left side of bottom grid |
| `LiveLogsCard` | Right side of bottom grid |
| `ProbeSnapshotCard` | Near Jobs panel |
| `JobsPanel` | Near Probe Stats |
| `WorkflowHistoryPanel` | Bottom of center pane |
| `WorkflowListPanel` | Workflow Rail (Surface 1) |
| `WorkflowDetailPanel` | Evidence Ledger (Surface 6) |

## Admin.tsx Pseudocode

```tsx
function Admin() {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);

  // Existing hooks for data fetching
  const { data: scheduler, refetch } = useQuery(['admin-session'], fetchAdminSession);
  const { data: workflows } = useQuery(['admin-workflows'], fetchWorkflows);
  const { data: selectedWorkflow } = useQuery(
    ['admin-workflow', selectedWorkflowId],
    () => fetchWorkflow(selectedWorkflowId),
    { enabled: !!selectedWorkflowId }
  );

  // Authorization check
  if (!isAuthorized) return <AdminUnlockPanel onUnlock={handleUnlock} />;
  if (!scheduler) return <Loader />;

  return (
    <div className="flex h-[calc(100vh-64px)] gap-0 bg-[#050505]">
      {/* Surface 1: Workflow Rail */}
      <aside className="hidden xl:flex w-80 flex-shrink-0 flex-col border-r border-gray-800">
        <WorkflowRail
          workflows={workflows}
          selectedId={selectedWorkflowId}
          onSelect={setSelectedWorkflowId}
        />
      </aside>

      {/* Surfaces 2-5: Center Column */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="p-6 space-y-6">
          {/* Header */}
          <AdminHeader scheduler={scheduler} onLock={handleLock} onRefresh={refetch} />

          {/* Overview KPIs */}
          <OverviewGrid cards={kpiCards} />

          {/* Control Console */}
          <ScannerWorkbench schedulerStatus={scheduler} onRefresh={refetch} />

          {/* Exclusions Panel */}
          <ExclusionsPanel />

          {/* Host Groups */}
          <HostGroupsPanel onChanged={refetch} />

          {/* World Map */}
          <div className="rounded-lg border border-gray-800 bg-[#111] p-4">
            <MapScopeToggle scope={mapScope} onChange={setMapScope} />
            <ScannerWorldMap {...geographyData} />
          </div>

          {/* Jobs Row */}
          <div className="grid gap-6 lg:grid-cols-2">
            <CurrentWorkflowCard currentJob={currentJob} />
            <JobsPanel workers={workers} jobs={jobs} onRefresh={refetchJobs} />
          </div>

          {/* History */}
          <WorkflowHistoryPanel {...historyData} />

          {/* Mobile Workflow List */}
          <div className="xl:hidden">
            <MobileWorkflowList
              workflows={workflows}
              onSelect={setSelectedWorkflowId}
            />
          </div>
        </div>
      </main>

      {/* Surface 6: Evidence Ledger */}
      <aside className="hidden 2xl:flex w-[26rem] flex-shrink-0 border-l border-gray-800">
        {selectedWorkflow ? (
          <EvidenceLedger workflow={selectedWorkflow} />
        ) : (
          <EmptyLedgerPrompt />
        )}
      </aside>
    </div>
  );
}
```

## Exclusions Panel Placement

The `ExclusionsPanel` goes in the center column, between `HostGroupsPanel` and the world map. It should be visible at all times, not hidden behind a tab.

## Evidence Ledger Behavior

- Always visible at ≥2xl breakpoint
- Populated when workflow selected in rail
- Shows empty state with "Select a workflow" prompt otherwise
- On mobile, accessible via tab or drawer

## Workflow Rail Component

```tsx
function WorkflowRail({ workflows, selectedId, onSelect }) {
  return (
    <div className="h-full flex flex-col bg-[#050505]">
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-gray-500">
          Workflows
        </div>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-900">
        {workflows.map((wf) => (
          <button
            key={wf.workflow_id}
            onClick={() => onSelect(wf.workflow_id)}
            className={clsx(
              "w-full text-left px-4 py-3 font-mono text-xs",
              "hover:bg-gray-900/50 transition-colors",
              wf.workflow_id === selectedId && "bg-green-900/15 border-l-2 border-l-green-500"
            )}
          >
            <div className="flex justify-between gap-2">
              <span className="truncate text-gray-300">{wf.strategy} // {wf.target}</span>
              <StatusBadge status={wf.status} />
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-gray-500">
              <span>{wf.current_stage ?? 'idle'}</span>
              <span>{formatAge(wf.started_at)}</span>
            </div>
            {wf.last_error && (
              <div className="mt-1 text-[10px] text-rose-400 truncate">{wf.last_error}</div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
```

## Evidence Ledger Component

```tsx
function EvidenceLedger({ workflow }) {
  return (
    <div className="h-full flex flex-col bg-[#050505]">
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-gray-500">
          Evidence Ledger
        </div>
        <div className="mt-1 text-sm text-gray-100 truncate">
          {workflow.strategy} // {workflow.target}
        </div>
        <div className="mt-2 space-y-0.5 text-[10px] font-mono text-gray-500">
          <div>Policy: <span className="text-gray-300">{workflow.policy_snapshot_hash?.slice(0, 16)}...</span></div>
          <div>Exclusions: <span className="text-gray-300">{workflow.exclude_snapshot_hash?.slice(0, 16)}...</span></div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {workflow.receipts.map((receipt) => (
          <StageReceiptCard key={receipt.receipt_id} receipt={receipt} />
        ))}
      </div>
    </div>
  );
}
```

## Implementation Priority

1. Restructure `Admin.tsx` to three-pane layout
2. Create `WorkflowRail` component
3. Create `EvidenceLedger` component
4. Add `ExclusionsPanel` component
5. Wire map scope toggle
6. Add mobile workflow list drawer