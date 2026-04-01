# Policy Engine

## Status
Draft — design phase

## Contract

The policy engine decides what Sintel is allowed to do, what it must refuse to do, and what additional controls it must apply.

Policy evaluation is mandatory before workflow start and at each stage boundary.

## Principles

### 1. Default deny for unsafe ambiguity

If a required fact is missing, the decision is deny or block, not allow.

### 2. Constitutional exclusions outrank everything

No policy can override the exclusion system. If exclusions are missing or empty, no discovery workflow may start.

### 3. Explain every decision

Every allow, deny, block, require-confirmation, and require-review decision must produce a machine-readable explanation.

### 4. Separate selection from authorization

The scheduler may propose work. Policy decides whether that work is allowed.

## Evaluation Types

```python
@dataclass(frozen=True)
class PolicyContext:
    workflow_id: str
    operator_id: str | None
    workflow_kind: str
    stage_name: str
    strategy: str
    target: str
    port: str
    egress_mode: str             # passive-only | tor-required | direct-egress-allowed
    exclude_snapshot_hash: str
    observed_metadata: dict      # country, provider, asn, labels, host count, etc.


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    effect: str                  # allow | deny | block | require-confirmation | require-review | redact
    policy_id: str
    reason: str
    details: dict
    evaluated_at: datetime


@dataclass(frozen=True)
class PolicyRule:
    policy_id: str
    scope: str                   # workflow | stage | observation | alert
    priority: int
    match: dict
    effect: str
    config: dict
```

## Policy Families

### Constitutional Policy

Hard rules that always apply:

- exclusions must exist
- exclusions must be non-empty
- all expanded targets must be filtered against exclusions
- no workflow may remove or bypass exclusion checks

### Strategy Policy

Controls which discovery strategies are allowed.

Examples:

- allow `shodan` always when API key exists
- allow `tor-connect` only when Tor stack is healthy
- block `masscan` when `OUR_GPUS_TOR_REQUIRED=true`
- require explicit operator confirmation for `masscan`

### Geography Policy

Controls region-based discovery, verification, or alerting.

Examples:

- deny active discovery against selected countries
- allow passive discovery only for specific regions
- require review before alert escalation for ambiguous geography

### Provider / Ownership Policy

Controls discovery or classification based on ASN owner, provider type, or organization.

Examples:

- deny active discovery of cloud hyperscalers unless explicitly approved
- deny residential IP verification
- downgrade severity for known internal testing ranges

### Rate / Blast Radius Policy

Controls operational volume.

Examples:

- cap `tor-connect` host expansion at 4096
- cap concurrent verifies per workflow
- cap daily unrestricted workflows per operator
- require cooldown windows between large workflows

### Automation Policy

Controls what unattended automation may do.

Examples:

- automation may run `shodan` but not `masscan`
- automation may classify but not alert without review
- automation may rerun known-safe workflows only within a budget

### Alert Policy

Controls when findings become operator-visible alerts.

Examples:

- create alert when a host is newly exposed and in a monitored group
- suppress alert when host belongs to an ignored group
- create escalation when a risky provider + region + model mix appears

## Evaluation Order

```
1. Constitutional policy
2. Strategy policy
3. Geography / provider policy
4. Rate / blast radius policy
5. Automation policy
6. Alert policy
```

Later families cannot override an earlier deny.

## Decision Semantics

### allow

The action may proceed.

### deny

The action is forbidden. Workflow cannot continue through this path.

### block

The action cannot proceed because required state is missing or unhealthy.

### require-confirmation

The action is permitted only after a human explicitly confirms the exact risk-bearing action.

### require-review

The action may proceed to a hold state but must not complete the next risky transition without review.

### redact

The action may proceed, but some data must be hidden or omitted in downstream views or exports.

## Policy Storage

```sql
CREATE TABLE policy_rules (
    policy_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    family TEXT NOT NULL,
    priority INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    match_json TEXT NOT NULL,
    effect TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE policy_decisions (
    decision_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    effect TEXT NOT NULL,
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL,
    evaluated_at DATETIME NOT NULL
);
```

## Example Rules

```yaml
- policy_id: constitutional.exclude.required
  family: constitutional
  priority: 0
  scope: workflow
  match: {}
  effect: block
  config:
    when_excludes_missing: true

- policy_id: strategy.masscan.direct-egress
  family: strategy
  priority: 10
  scope: workflow
  match:
    strategy: masscan
    egress_mode: tor-required
  effect: deny
  config:
    reason: direct egress disabled while tor-required mode is active

- policy_id: geography.active.denied-countries
  family: geography
  priority: 20
  scope: workflow
  match:
    strategy: [tor-connect, masscan]
    country_in: ["CN", "RU"]
  effect: require-review
  config:
    reviewer_group: defense-ops
```

## Operator Experience

The UI must answer:

- why did this workflow start?
- why was this workflow blocked?
- which policy allowed or denied it?
- which confirmation was required?
- which future actions are still permitted?

Policy is not a hidden backend concern. It is a first-class operator surface.

## Current Mapping

Current controls already exist in partial form:

- environment flags such as `OUR_GPUS_TOR_REQUIRED`
- strategy-specific caps like Tor max hosts
- exclusion file loading and fail-closed behavior
- admin-only workflow start paths

The policy engine should absorb these controls into explicit policy decisions so the system can explain itself.

## Integration Points

- **workflow engine** calls policy before start and before each stage transition
- **command center UI** shows matched rules and decisions
- **Threat Radar** can feed risk labels into observation-level policy checks
- **eta-mu** can receive blocked/review-required workflow events
