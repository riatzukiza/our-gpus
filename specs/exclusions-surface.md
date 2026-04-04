# Exclusions Surface

## Status
Draft — design phase

## Contract

Exclusions are constitutional: no workflow runs if exclusions are missing or empty. The exclusions surface makes this constraint visible and auditable.

## Purpose

The exclusions surface serves three functions:

1. **Visibility**: Show what networks are protected from scanning
2. **Audit**: Prove to operators (and auditors) that exclusions were applied
3. **Refresh**: Allow operators to trigger dynamic exclusion updates

## Exclusion Sources

### Static Exclusions

File: `excludes.conf`

Contains manually-curated CIDRs that should never be touched:

- IANA reserved ranges (RFC 5735, RFC 6598)
- Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-local (169.254.0.0/16)
- Documentation/example ranges
- User-specified protected networks

### Dynamic Exclusions

File: `excludes.generated.conf`

Contains programmatically-discovered CIDRs:

- Provider IP ranges (AWS, GCP, Azure, Cloudflare, etc.)
- CDN networks
- Known safe infrastructure

Dynamic exclusions can be refreshed without redeploying.

## Backend API

### Get Exclusions

```
GET /api/admin/excludes
→ {
     static_excludes: string[],
     dynamic_excludes: string[],
     effective_count: number,
     last_refreshed_at: string | null,
     source_hash: string
   }
```

### Refresh Dynamic Exclusions

```
POST /api/admin/excludes/dynamic/refresh
→ { refreshed: boolean, count: number, refreshed_at: string }
```

## Frontend Component

### ExclusionsPanel

Location: Admin center column, after Host Groups, before Map

```
┌─────────────────────────────────────────────────────────────────────┐
│ Constitutional Exclusions                              [Refresh Dyn] │
│                                                                     │
│ CIDRs and networks the system will never touch.                    │
│ No workflow runs if this set is empty.                             │
│                                                                     │
│ ┌─────────────────────────┐ ┌─────────────────────────────────────┐│
│ │ Static Exclusions       │ │ Effective: 847 CIDRs                 ││
│ │ 10.0.0.0/8              │ │ Dynamic refreshed: 3 hours ago       ││
│ │ 172.16.0.0/12           │ │                                     ││
│ │ 192.168.0.0/16          │ │ These exclusions are applied to all ││
│ │ 169.254.0.0/16          │ │ discovery strategies. They are a     ││
│ │ ...                     │ │ constitutional layer and cannot be  ││
│ │                         │ │ bypassed by workflows.              ││
│ └─────────────────────────┘ └─────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### Design Notes

- Read-only view of effective exclusions (editing requires admin unlock)
- Prominent display of effective count
- Last-refreshed timestamp for dynamic exclusions
- Clear constitutional banner explaining the rules
- No "delete" or "bypass" actions — those don't exist in the system

## Safety Properties

1. Empty exclusions = no workflows start
2. Exclusion snapshot hash is recorded in every workflow
3. Exclusion changes require explicit admin action
4. No automation can modify exclusions without human approval

## Provenance

Every workflow stores:

- `exclude_snapshot_hash`: SHA-256 of merged exclusions at workflow start
- This hash is displayed in the Evidence Ledger

## Future Enhancements

1. **Exclusion Groups**: Named groups of exclusions for different contexts
2. **Audit Log**: Full history of exclusion changes with who/when/why
3. **Import from URL**: Fetch static exclusions from a remote source
4. **Provider Auto-Detection**: Automatically detect and exclude hosting ranges