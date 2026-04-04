# Leads Management

## Status
Draft — design phase

## Contract

Leads are the product's central output: enriched, scored, clusterable opportunities for contact and remediation. A lead is not just a raw IP; it's an evaluated entity ready for human or automated follow-up.

## Lead Entities

### Core Types

- **Asset**: Single IP+port/domain/host observation
- **LeadRecord**: An opportunity, clustered assets + enrichment result + contact routes
- **CampaignCluster**: Grouping for outreach planning (by region, ASN, org, etc.)
- **Contact**: Reachable public contact endpoint with type and confidence

### Lead Statuses

| Status | Meaning |
|--------|---------|
| `NEW` | Unreviewed, fresh from enrichment |
| `REVIEWED` | Human has inspected, disposition pending |
| `APPROVED` | Ready for outreach |
| `SUPPRESSED` | Explicitly excluded from outreach |
| `EXPORTED` | Sent to downstream (CSV, webhook, CRM) |

### Recommended Routes

| Route | Meaning |
|-------|---------|
| `SECURITY_TXT` | Use /.well-known/security.txt contact |
| `RDAP_ABUSE` | Use RDAP/WHOIS abuse contact |
| `WEBSITE_SECURITY` | Use website /security or /contact security form |
| `WEBSITE_GENERAL` | Use general business contact page |
| `PROVIDER_ABUSE` | Use hosting provider's abuse desk |
| `MANUAL_REVIEW` | No confident route; needs human judgment |

## Lead Score Components

A lead score (0-100) is composed of:

- **Scanner Signal**: What was observed (Ollama on 11434, etc.)
- **Org Quality**: Confidence in org resolution from RDAP/cert/PTR
- **Contact Quality**: Security.txt presence, verified role accounts
- **Geo Relevance**: Alignment with target regions/priorities
- **Freshness**: How recent the observation is

Score is used for prioritization, not as ground truth.

## Leads Page Layout

### Split-Pane Master/Detail

```
┌──────────────────────────────────────────────────────────────────────┐
│  [Status Filters]  [Route Filter]  [Search]  [Has Contacts Toggle]   │
├──────────────────────────────────────────────────────────────────────┤
│  Lead List (Left)              │  Lead Detail (Right)               │
│                                │                                     │
│  ┌────────────────────────────┐│  ┌─────────────────────────────────┐│
│  │ Status │ Asset │ Org │ Score││  │ Overview │ Evidence │ Contacts ││
│  │ NEW    │ acme  │ Acme│ 78   ││  │                                 ││
│  │ REVIEW │ 1.2.x │ XYZ │ 65   ││  │ Asset summary                   ││
│  │ ...                        ││  │ Org resolution                  ││
│  └────────────────────────────┘│  │ Evidence trail                  ││
│                                │  │ Contact routes                  ││
│  [Batch Actions]               │  │ Activity history                ││
│                                │  └─────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### Lead Detail Tabs

1. **Overview**: Asset info, org resolution, score breakdown
2. **Evidence**: Chronological `EvidenceStep[]` with source, confidence, notes
3. **Contacts & Route**: Recommended route explanation, contact table with confidence
4. **Activity**: Status change history, notes, export logs

## Actions

### Single-Lead Actions

- **Approve**: Set status `APPROVED`, record note
- **Suppress**: Set status `SUPPRESSED`, record reason
- **Mark Exported**: Set status `EXPORTED`, optionally POST to webhook
- **Add Note**: Append to activity log

### Batch Actions

- Mark selected as `APPROVED` / `SUPPRESSED` / `EXPORTED`
- Export selected to CSV
- Route selected to webhook

## Evidence Model

Each lead carries `EvidenceStep[]`:

| Evidence Type | Source | Meaning |
|---------------|--------|---------|
| `ASSET_OBSERVATION` | Scanner | Raw port/service observation |
| `RDAP_NETWORK` | RDAP | IP network registration |
| `RDAP_ENTITY` | RDAP | Organization/entity from RDAP |
| `TLS_CN` | Certificate | Certificate common name |
| `TLS_SAN` | Certificate | Subject alternative names |
| `SECURITY_TXT_CONTACT` | HTTP | Contact from security.txt |
| `WEBSITE_CONTACT` | HTTP | Contact from public pages |
| `ORG_MATCH` | Resolution | Inferred org association |
| `GEO_MATCH` | Geo | Geographic classification |

Evidence is append-only. Resolution can update, but history is preserved.

## Saved Views

Operators should be able to save and recall filters:

- "High-GPU Clusters": GPU density > threshold, cluster lead type
- "US Enterprise Targets": Country=US, org confidence > 0.7
- "No Contact Yet": No contacts with confidence > 0.5
- "Needs Manual Review": Route = `MANUAL_REVIEW`

## API Contracts

### List Leads

```
GET /api/leads?status=NEW&route=SECURITY_TXT&has_contacts=true&page=0&size=50
→ PaginatedLeadRecordResponse
```

### Get Lead Detail

```
GET /api/leads/{id}
→ LeadDetailResponse (full object with evidence, contacts, activity)
```

### Update Status

```
POST /api/leads/{id}/status
Body: LeadStatusUpdateRequest { status, notes }
→ LeadRecordResponse
```

### Batch Update

```
POST /api/leads/batch/status
Body: { lead_ids: string[], status: LeadStatus, notes?: string }
→ { updated: number }
```

### Export

```
GET /api/leads/export?status=APPROVED&format=csv
→ CSV download
```

## Next Steps

1. Implement `LeadsTable.tsx` with status/route/search filters
2. Implement `LeadDetail.tsx` with four tabs
3. Add batch action bar
4. Wire to backend endpoints for leads and evidence
5. Add saved views storage (localStorage or backend)