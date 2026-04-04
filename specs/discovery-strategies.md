# Discovery Strategies

## Status
Draft — design phase

## Contract

Every discovery strategy implements the same interface:

```python
class DiscoveryStrategy(ABC):
    name: str
    risk_tier: str  # passive, bounded, unrestricted

    @abstractmethod
    def execute(
        self,
        target: str,
        port: str,
        exclude_file: str,
        **kwargs,
    ) -> DiscoveryResult: ...


@dataclass(frozen=True)
class DiscoveryResult:
    strategy: str
    target: str
    port: str
    exclude_snapshot_hash: str
    observations: list[HostObservation]
    attempted_hosts: int
    discovered_hosts: int
    elapsed_seconds: float
    metadata: dict
```

Every strategy must:

- accept a target CIDR or query string
- accept the merged exclusion file path(s)
- fail closed if exclusions are missing or empty
- produce `DiscoveryResult` with `exclude_snapshot_hash` populated
- log its blast radius before executing
- produce `HostObservation` records for each discovered host

## Strategies

Note: the current implementation still exposes `tor` in some API payloads and UI state. In the Sintel spec set, the canonical strategy name is `tor-connect`. `tor` should be treated as a transitional alias until the API is renamed.

### shodan — Passive Discovery

**Risk tier:** passive

**Mechanism:** Query the Shodan API using exclusion-derived search queries. No packets are sent from our infrastructure.

**Inputs:**
- `target`: IP range or subnet to filter Shodan results against
- `port`: port to query for
- `exclude_file`: merged exclusion file path
- `base_query`: additional Shodan search terms (e.g. `product:Ollama`)
- `max_queries`: maximum number of queries to execute
- `page_limit`: pages per query
- `max_matches`: host cap

**Blast radius:**
- zero outbound packets
- cost: Shodan API credits only
- cannot trigger abuse complaints

**Output:** `HostObservation` with `discovery_strategy: shodan`

---

### tor-connect — Bounded Active Discovery

**Risk tier:** bounded

**Mechanism:** After exclusion filtering, expand the target into allowed IPs. Then perform bounded concurrent TCP connect attempts to `<ip>:<port>` through the Tor relay stack.

**Inputs:**
- `target`: CIDR range
- `port`: port to check
- `exclude_file`: merged exclusion file path
- `max_hosts`: maximum expanded host count (default 4096)
- `concurrency`: parallel connection limit (default 32)
- `timeout_seconds`: per-connection timeout (default 5)
- `retries`: per-host retry count (default 2)

**Constraints:**
- host expansion must fail closed if count exceeds `max_hosts`
- must filter every expanded host against exclusions
- must not send traffic to excluded hosts under any circumstance
- must emit per-host probe attempt to log file for operator review
- must not probe more than `max_hosts` hosts per run

**Blast radius:**
- outbound TCP connections through Tor
- Tor exit IP carries the scan origin
- logs are the only record of which hosts were contacted

**Output:** `HostObservation` with `discovery_strategy: tor-connect`

---

### wireguard-connect — Planned Operator-Controlled VPN Discovery

**Risk tier:** bounded

**Mechanism:** Planned future strategy. Like `tor-connect`, this performs bounded active HTTP/TCP discovery, but routes through an operator-controlled WireGuard tunnel instead of Tor exits.

**Status:** spec only, not deployed.

**Reference:** `specs/wireguard-connect-strategy.md`

---

### masscan — Unrestricted Port Discovery

**Risk tier:** unrestricted

**Mechanism:** Run raw `masscan` packet scanner with exclusion file. This is the only strategy that performs actual network-layer port scanning.

**Inputs:**
- `target`: CIDR range
- `port`: port to scan
- `exclude_file`: merged exclusion file path
- `rate`: packet rate (default 100k)
- `router_mac`: local router MAC
- `strategy_name`: always `masscan`

**Constraints:**
- blocked when Tor mode requires no direct egress
- must pass `--exclude-file` to masscan
- must fail closed if exclusions are missing
- must log full command and output
- must produce `exclude_snapshot_hash` in result
- must write merged exclude file before scanning

**Blast radius:**
- raw packet scan from our IP
- any traffic we send carries our source address
- unsolicited SYN packets to target hosts
- highest complaint potential
- requires highest operator awareness

**Output:** `HostObservation` with `discovery_strategy: masscan`

## Strategy Hierarchy

```
passive        < bounded        < unrestricted

shodan         < tor-connect / wireguard-connect < masscan
zero packets   < TCP connects                  < raw SYN scan
Shodan cost    < indirect controlled egress    < direct egress
no complaints  < bounded active                < direct complaints
```

## Strategy Selection Rules

1. `shodan` is always available (if API key configured)
2. `tor-connect` is available when Tor stack is running
3. `masscan` is available only when:
   - Tor mode does not require fail-closed egress
   - `MASSCAN_ALLOW_DIRECT_EGRESS` is not `false`
   - operator explicitly confirms risk

## Downstream Stage Interface

All strategies produce the same output type and feed into the same downstream pipeline:

```
discover
  → ingest
    → verify
      → geocode
        → graph-emit
          → classify/group
            → alert
```

The discovery strategy is a pluggable input to this pipeline. The pipeline does not change behavior based on which strategy produced the observation — it only records the strategy name in provenance.
