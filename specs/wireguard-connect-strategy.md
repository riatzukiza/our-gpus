# WireGuard Connect Strategy

## Status
Draft — planning only, not approved for deployment

## Purpose

Add a fourth discovery strategy, `wireguard-connect`, that routes bounded active HTTP/TCP discovery through an operator-controlled WireGuard tunnel instead of Tor or direct egress.

This spec exists to get the design on the books. It does **not** authorize deployment, purchase, or third-party VPN use today.

## Why This Exists

`tor-connect` gave us two useful lessons:

1. indirect/shared egress can materially distort discovery yield
2. scanner transport needs to be operator-controllable and measurable

We want an alternate bounded-active strategy with these properties:

- less noisy than Tor
- more controllable than public/shared VPN providers
- safer than raw direct `masscan`
- reproducible enough for canary-based recall testing

## Non-Goals

This spec does **not** cover:

- immediate deployment
- buying or renting infrastructure now
- bundling support for public free/shared VPN services
- replacing `tor-connect`, `shodan`, or `masscan`
- turning WireGuard into a packet-scan strategy; this remains an application-layer connect strategy

## Canonical Strategy Name

`wireguard-connect`

Rationale:
- matches `tor-connect`
- makes clear that the strategy performs bounded connect-style discovery
- keeps the transport separate from downstream ingest/probe/geocode stages

## Risk Tier

`bounded`

Blast radius is lower than direct `masscan`, but higher than `shodan`.
Traffic originates from a controlled WireGuard exit rather than Tor exits or our raw local IP.

## Contract

The strategy must implement the same discovery interface as the other strategies.

```python
class DiscoveryStrategy(ABC):
    name: str
    risk_tier: str

    @abstractmethod
    def execute(
        self,
        target: str,
        port: str,
        exclude_file: str,
        **kwargs,
    ) -> DiscoveryResult: ...
```

`wireguard-connect` must:

- accept the same target semantics as `tor-connect`
- fail closed if exclusions are missing or empty
- filter every expanded host against exclusions before any network attempt
- support bounded host expansion with `max_hosts`
- support bounded concurrency with `concurrency`
- produce normal `DiscoveryResult` / `ScanExecutionResult`
- record transport provenance in logs and workflow metadata
- fail closed if the WireGuard tunnel is not healthy or if traffic is not provably routed through the tunnel

## Desired Behavior

For a bounded list of IPs or CIDRs, the strategy should:

1. expand targets to allowed hosts
2. verify the WireGuard tunnel is up and selected
3. verify fail-closed egress rules are active
4. perform HTTP-based Ollama detection (`/api/tags`, or root-path health where explicitly configured)
5. emit discovered `ip:port` lines in the same ingest-friendly format as `tor-connect`
6. annotate logs/metrics with WireGuard-specific transport facts

## Operator Model

This strategy assumes an **operator-controlled** exit, not a public VPN pool.

Acceptable future deployment shapes:

- self-hosted VPS with WireGuard server
- trusted remote host with dedicated egress identity
- multiple operator-managed WireGuard exits by geography/provider

Rejected for this strategy:

- public free/shared VPN services as primary scanner transport
- opaque consumer VPN apps with no routing proofs
- tunnels that cannot support fail-closed enforcement

## Architecture

### 1. Transport layout

Scanner container(s) route outbound Internet traffic through a WireGuard interface.

Preferred shape:

- new compose overlay for WireGuard sidecar/container
- scanner traffic routed through that sidecar or network namespace
- API/worker can opt into the strategy without global host routing changes

Candidate topologies:

#### A. Shared sidecar namespace
- dedicated `wireguard-egress` container owns the tunnel
- scanner container joins that network namespace
- easiest place to enforce kill-switch rules

#### B. In-container WireGuard
- API/worker container brings up `wg0` itself
- simpler conceptual model, worse isolation
- less desirable

#### C. Probe relay over WireGuard
- strategy sends probe jobs to a sidecar already pinned to WireGuard
- strongest separation of concerns
- slightly more moving parts

**Preferred plan:** C first if we want isolation, A if we want simpler ops.

### 2. Fail-closed routing

The design must prevent silent fallback to direct egress.

Required properties:

- if tunnel is down, strategy errors immediately
- if route table is wrong, strategy errors immediately
- if kill-switch rules are absent, strategy errors immediately
- healthcheck must prove the active egress identity matches the selected WireGuard exit

Examples of proof checks:

- route lookup for a public IP resolves to `wg0`
- external egress-IP check matches expected exit identity
- iptables/nftables kill-switch present and active

### 3. Discovery method

Like `tor-connect`, this remains a bounded application-layer detection strategy.

Default detection path:
- `GET http://<ip>:11434/api/tags`

Optional future fallback:
- `GET /` if explicitly enabled for canary/diagnostic mode only

### 4. Exit identity

Each exit should have stable metadata:

- `exit_id`
- provider / host label
- country / region
- expected public IP or IP set
- health status
- last verified timestamp

This enables per-exit yield accounting and replayable diagnostics.

## Config Surface

### Required config

```env
OUR_GPUS_DEFAULT_STRATEGY=wireguard-connect
WIREGUARD_ENABLED=true
WIREGUARD_PROFILE=default
WIREGUARD_CONFIG_PATH=/run/secrets/our-gpus-wireguard.conf
WIREGUARD_EXPECTED_EGRESS_IP=203.0.113.10
WIREGUARD_HEALTHCHECK_URL=https://ifconfig.me/ip
WIREGUARD_FAIL_CLOSED=true
```

### Strategy-level knobs

```python
wireguard_max_hosts: int = 4096
wireguard_concurrency: int = 16
wireguard_timeout_seconds: int = 5
wireguard_retries: int = 2
wireguard_profile: str | None = None
wireguard_expected_egress_ip: str | None = None
```

### Future optional knobs

- `wireguard_probe_path` default `/api/tags`
- `wireguard_wave_size`
- `wireguard_wave_pause_ms`
- `wireguard_exit_id`
- `wireguard_dns_mode`

## API / UI Impact

### Backend

Add `wireguard-connect` to:

- strategy normalization
- strategy map
- scanner config endpoint
- start-scan request schema
- ACO scheduler config only if/when explicitly supported

### Frontend

Admin UI should expose:

- strategy option: `wireguard-connect`
- selected WireGuard profile / exit
- health state of the tunnel
- last verified egress IP

### Workflow metadata

Persist in scan/workflow stats:

- `strategy=wireguard-connect`
- `wireguard_profile`
- `wireguard_exit_id`
- `wireguard_expected_egress_ip`
- `wireguard_verified_egress_ip`
- `transport_health`

## Observability Requirements

Every run must log enough to debug transport truthfully.

Minimum log fields:

- strategy
- target
- allowed_hosts
- concurrency
- timeout / retries
- wireguard profile
- exit id
- expected egress IP
- observed egress IP
- route verification status
- kill-switch verification status
- discovered_hosts
- per-status counts (`status_200`, `status_503`, etc.)
- transport errors (`error_ReadTimeout`, `error_ConnectError`, etc.)

## Safety / Policy Constraints

The strategy must preserve current scanner safety invariants:

- exclusions are mandatory
- no probing excluded hosts
- bounded host count
- bounded concurrency
- operator-visible blast radius
- no silent direct fallback

Additional WireGuard-specific constraint:

- only operator-managed exits are allowed

## ACO Integration

Not phase-1.

Initial support should be **one-off/manual only**.

Why:
- we need transport characterization before letting ACO depend on it
- we need per-exit reliability data first
- scheduler heuristics should not mix transport failures with block-yield failures

Future ACO support can be added only after:

- canary stability is acceptable
- route verification is solid
- per-exit observability exists
- failure semantics are clearly separated from zero-yield scans

## Delivery Phases

### Phase 0 — Spec only
- create this spec
- choose canonical name
- define fail-closed invariants
- do not deploy

### Phase 1 — Transport harness
- add disposable WireGuard canary harness outside app
- verify exact-IP batches through the tunnel
- compare direct vs tor vs wireguard on known-positive canaries
- capture recall/variance receipts

### Phase 2 — Backend strategy scaffold
- add strategy enum/config/schema support
- add healthcheck and route verification primitives
- keep behind explicit operator flag
- no default selection

### Phase 3 — One-off strategy implementation
- run manual scans only
- emit full transport diagnostics
- no ACO usage yet

### Phase 4 — UI and operator controls
- show tunnel health / exit identity
- show last verified egress IP
- expose canary run action and diagnostics

### Phase 5 — Optional ACO support
- only after canary results justify it
- only with transport-aware observability and gating

## Verification Plan

Before any real rollout, require these checks:

### Canary tests
- fixed IP batch of known-positive Ollama hosts
- repeated trials at multiple concurrency levels
- compare direct / tor / wireguard yields
- require low variance before promotion

### Route integrity tests
- verify outbound public IP through tunnel
- verify failure when tunnel is intentionally dropped
- verify no direct fallback when tunnel is unavailable

### Safety tests
- exclusions still apply under WireGuard mode
- oversized host expansions still fail closed
- strategy refuses to run without verified route state

### Operational tests
- container restart preserves tunnel configuration
- health endpoint reflects actual tunnel status
- logs include exit identity and verification data

## Promotion Gates

`wireguard-connect` can move from draft to implementation-ready only if:

- we have an operator-managed exit
- fail-closed route enforcement is designed concretely
- exact-IP canary runs outperform or at least stabilize relative to Tor
- observability is sufficient to distinguish transport loss from target scarcity

It can become a default strategy only if:

- repeated canary batches show materially better recall than `tor-connect`
- variance is acceptable across runs
- operator cost/risk remains acceptable

## Open Questions

- Should WireGuard live in a dedicated sidecar, or should probes be delegated to a WG-bound relay?
- Do we want one global exit or multiple labeled exits by geography/provider?
- Should DNS resolution happen inside the tunnel, or should all probes remain IP-only?
- Should the strategy support only `/api/tags`, or also a configurable root-path canary mode?
- What recall threshold is good enough to justify ACO integration?

## Recommendation

Keep this as a planned strategy and prioritize it over public/shared VPN integration.

If we implement a 4th active strategy, `wireguard-connect` should be the canonical path because it gives us:

- controlled egress identity
- better diagnostics
- safer policy boundaries
- a realistic chance of better recall than Tor without falling back to raw direct scanning
