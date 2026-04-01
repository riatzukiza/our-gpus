# Safety Model

## Status
Draft — design phase

## Contract

Sintel is a governed infrastructure signals system. Safety is not a best-effort guideline layered on top of scanning. It is the system's execution boundary.

## Safety Invariants

### 1. Exclusions are constitutional

If the effective exclusion set is missing or empty, discovery does not run.

This applies to:

- one-off workflows
- continuous scheduler workflows
- passive query plans that depend on exclusion-derived filters
- active verification derived from discovery outputs

### 2. No hidden egress mode changes

The system must always know whether it is in:

- passive-only mode
- Tor-required mode
- direct-egress-allowed mode

Strategy availability depends on this mode and must be operator-visible.

### 3. Provenance before trust

A discovery without provenance is not a valid Sintel observation.

Every workflow and observation must carry:

- strategy
- operator or automation identity
- exclusion snapshot hash
- policy snapshot hash
- timestamps
- evidence refs

### 4. Risk tier must match operator intent

The selected strategy must honestly represent the kind of activity happening.

- `shodan` = passive
- `tor-connect` = bounded active connect
- `masscan` = unrestricted raw packet scan

No euphemistic labels.

### 5. Automation is less trusted than humans

Automation may only execute workflows within explicitly defined budgets and policy scopes.

### 6. Failure must be safe

When a prerequisite is missing or uncertain, the system blocks or degrades to a safer path.

## Threat Model

The system must protect against:

- accidental scanning of excluded networks
- direct egress when Tor-required mode should fail closed
- operator confusion about which strategy actually ran
- silent policy drift
- workflows that cannot be reconstructed later
- alerting based on weak or missing evidence

## Risk Tiers

| Tier           | Strategy      | Safety posture |
|----------------|---------------|----------------|
| passive        | `shodan`      | lowest network risk, still requires provenance and policy |
| bounded active | `tor-connect` | limited host expansion, capped concurrency, Tor egress |
| unrestricted   | `masscan`     | highest risk, explicit approval and direct egress controls |

## Required Safety Checks

### Before workflow start

- exclusions present and non-empty
- policy snapshot resolved
- strategy available in current egress mode
- target parses successfully
- risk tier acknowledged if required

### Before active discovery

- every target host filtered through exclusions
- host expansion within policy cap
- egress mode matches strategy
- logging destination writable

### Before alert creation

- evidence exists
- workflow provenance is complete
- classification source is known
- alert policy allows escalation

## Blast Radius Controls

The system must constrain scale, not only intent.

Examples:

- host expansion caps for `tor-connect`
- explicit rate controls for `masscan`
- concurrency controls for verify
- cooldown windows for repeated workflows
- per-operator and per-automation budgets

## Accountability Model

Every risky workflow needs attributable authorship.

Questions the system must always be able to answer:

- who started this workflow?
- what exact config did they use?
- what exclusions were active?
- what policy permitted it?
- what did the system contact?
- what evidence was produced?

## Safe Degradation Rules

When a dependency is unhealthy, the system should prefer a safer mode when possible.

Examples:

- if Tor stack is unavailable, `tor-connect` becomes unavailable rather than falling back to direct egress
- if Shodan API key is missing, passive discovery is unavailable rather than silently switching strategies
- if graph emission fails, workflow can complete with a failed `graph-emit` receipt, but no success should be implied

## Unsafe Patterns That Are Forbidden

- running with an empty exclusion file
- bypassing exclusion checks for convenience
- auto-falling back from Tor-routed activity to direct egress
- relabeling `masscan` as a low-risk or safe path
- mutating observations in place without append-only evidence
- creating alerts with no evidence chain

## Operator UX Requirements

Safety must appear in the UI, not only in docs.

The UI must show:

- current egress mode
- strategy risk tier
- exclusion snapshot hash
- policy decisions
- confirmation requirements
- blocked reasons

## Current Mapping

Current pieces already implement part of this model:

- exclusion fail-closed behavior in scan path construction
- `OUR_GPUS_TOR_REQUIRED` and `MASSCAN_ALLOW_DIRECT_EGRESS` gating
- shared admin workflow controls with Tor preselected
- per-strategy knobs that constrain blast radius

The missing work is to elevate these checks into explicit workflow validation, policy decisions, and visible receipts.

## Safety Outcome

Sintel should make it easier to do the governed thing than the risky thing.

If an operator tries to act outside the safety model, the system should refuse clearly, explain why, and preserve the refusal as part of the audit trail.
