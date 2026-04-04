# Evidence Ledger Surface

## Status
Draft — design phase

## Contract

The evidence ledger proves what the system saw and what it did. It surfaces the full provenance chain for every observation and workflow.

## Purpose

1. **Accountability**: Every claim has a source
2. **Audit**: Operators can trace any result back to evidence
3. **Trust**: Shows the system isn't making things up

## Evidence Types

| Type | Source | What it proves |
|------|--------|----------------|
| `ASSET_OBSERVATION` | Scanner | Port X was open at Y time |
| `RDAP_NETWORK` | RDAP | IP belongs to network N |
| `RDAP_ENTITY` | RDAP | Network registered to entity E |
| `RDAP_CONTACT` | RDAP | Contact C found in registration |
| `PTR` | DNS | PTR record resolved to hostname |
| `TLS_CN` | TLS | Certificate has CN |
| `TLS_SAN` | TLS | Certificate has SANs |
| `SECURITY_TXT_CONTACT` | HTTP | security.txt had contact |
| `SECURITY_TXT_POLICY` | HTTP | security.txt had policy URL |
| `WEBSITE_CONTACT` | HTTP | Website had contact method |
| `ORG_MATCH` | Resolution | Org inferred from evidence |
| `GEO_MATCH` | Geo | Geographic classification |
| `MANUAL_NOTE` | Operator | Human-added note |

## Stage Receipts

Every workflow stage produces a receipt:

```typescript
interface WorkflowStageReceipt {
  receipt_id: string;
  workflow_id: string;
  stage_name: string;
  status: 'pending' | 'running' | 'complete' | 'failed' | 'blocked';
  started_at: string;
  finished_at: string | null;
  metrics: Record<string, number | string>;
  evidence_refs: string[];
  error_message: string | null;
}
```

### Stage Names

| Stage | Meaning |
|-------|---------|
| `discover` | Host discovery complete |
| `ingest` | Hosts ingested into store |
| `verify` | Verification probes complete |
| `geocode` | Geo lookup complete |
| `enrich` | Enrichment (RDAP, TLS, security.txt) complete |
| `resolve` | Organization resolution complete |
| `graph-emit` | Graph edges emitted |
| `classify` | Lead classification complete |
| `alert` | Alerts generated |

## Workflow Provenance

Every workflow carries:

```typescript
interface WorkflowProvenance {
  workflow_id: string;
  strategy: Strategy;
  target: string;
  port: number;

  // Constitutional layer
  policy_snapshot_hash: string;
  exclude_snapshot_hash: string;

  // Operator context
  triggered_by: string;  // operator ID or automation ID
  triggered_at: string;

  // Configuration
  config_snapshot: Record<string, any>;
}
```

## Evidence Ledger UI

### Right-Hand Panel Layout

```
┌─────────────────────────────────────────────────┐
│ Evidence Ledger                                  │
│ Workflow: abc123                                 │
│ tor-connect // 192.0.2.0/24 // 11434           │
│                                                  │
│ Policy:     sha256:a1b2c3...                     │
│ Exclusions: sha256:d4e5f6...                     │
│                                                  │
│ ┌────────────────────────────────────────────────┤
│ │ DISCOVER (complete)                   3m ago  │
│ │   hosts_discovered: 847                        │
│ │   Evidence: [discover_abc123.json]             │
│ │                                                │
│ │ INGEST (complete)                      2m ago  │
│ │   hosts_ingested: 847                          │
│ │   duplicates_skipped: 23                       │
│ │                                                │
│ │ VERIFY (complete)                      1m ago  │
│ │   probes_sent: 400                              │
│ │   successful: 310                               │
│ │   failed: 90                                   │
│ │   Evidence: [verify_log_abc123.json]          │
│ │                                                │
│ │ GEOCODE (complete)                     30s ago  │
│ │   geocoded: 310                                │
│ │                                                │
│ │ ENRICH (running)                       now     │
│ │   rdap_complete: 120                           │
│ │   rdap_pending: 190                            │
│ │   tls_complete: 80                              │
│ │   security_txt_checked: 200                    │
│ └────────────────────────────────────────────────┤
│                                                  │
│ [View Raw Logs] [Export Evidence Package]       │
└─────────────────────────────────────────────────┘
```

## Evidence Reference Format

Evidence references are URIs pointing to stored artifacts:

```
evidence://workflow/{workflow_id}/stage/{stage}/{type}/{id}
```

Examples:

- `evidence://workflow/abc123/stage/discover/scan_result/001`
- `evidence://workflow/abc123/stage/enrich/rdap/192.0.2.1`
- `evidence://workflow/abc123/stage/enrich/security_txt/example.com`

## Evidence Package Export

For audit or legal requests, the system can export:

```
POST /api/admin/workflows/{id}/export-evidence
→ {
     package_url: string,  // signed S3 URL or similar
     package_hash: string,
     expires_at: string
   }
```

Package contains:

- All stage receipts
- All referenced evidence files
- Provenance metadata
- Exclusion and policy snapshots used

## Provenance Guarantee

The system must always be able to answer:

1. Who triggered this workflow?
2. What exact configuration was used?
3. What exclusions were active (hash)?
4. What policy was active (hash)?
5. What hosts were contacted?
6. What evidence was produced?
7. What did each stage output?

## Integration with Graph

When an observation emits to the graph, it carries:

- `workflow_id`: Which workflow produced this observation
- `receipt_id`: Which stage receipt
- `evidence_ref`: Direct link to evidence artifact

This allows the graph to trace any edge back to its source.