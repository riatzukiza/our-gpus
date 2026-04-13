# Shodan Strategy

## Status
Draft — design phase

## Contract

Shodan is a passive discovery strategy. It queries Shodan's API for known hosts matching search criteria, producing observations without any direct network contact.

## Classification

| Property | Value |
|----------|-------|
| Type | Passive |
| Risk | Lowest |
| Trust | High (with API key) |
| Egress | API only, no direct host contact |

## Behavior

### Input

- Shodan API key
- Search query (port, product, country filters, etc.)
- Exclusions (applied as post-filter to results)

### Process

1. Construct Shodan query from target + filters
2. Execute Shodan API search
3. Filter results against merged exclusions
4. Transform Shodan results to host observations
5. Return host list

### Output

Host observations with:

- IP
- Port
- Product/service
- Version (if available)
- Country
- ASN
- Timestamp

## Safety Properties

1. **No direct network contact**: All discovery happens via Shodan API
2. **Egress limited to api.shodan.io**: No arbitrary outbound connections
3. **Exclusions still apply**: Results filtered before ingestion
4. **Provenance recorded**: Query string, API key hash, result hash stored

## API Integration

### Query Construction

```
target + port + filters + exclusions
→ Shodan query string
```

Example:

```
port:11434 product:"Ollama" country:US -net:10.0.0.0/8
```

### Shodan Client

```python
class ShodanStrategy(DiscoveryStrategy):
    def __init__(self, api_key: str, exclusions: ExclusionSet):
        self.client = shodan.Shodan(api_key)
        self.exclusions = exclusions

    async def discover(self, target: DiscoveryTarget) -> List[HostObservation]:
        query = self._build_query(target)
        results = await self._search(query)
        hosts = self._parse_results(results)
        hosts = self._apply_exclusions(hosts)
        return hosts
```

## Rate Limits

Shodan has query limits based on API tier. The strategy must:

- Respect rate limits
- Handle pagination for large result sets
- Handle API errors gracefully
- Log query count for accountability

## Error Handling

| Error | Response |
|-------|----------|
| Rate limited | Wait and retry with exponential backoff |
| Invalid API key | Fail immediately, log error |
| Query error | Log query, return empty results |
| No results | Return empty list, not error |

## Provenance

Every observation from Shodan includes:

```json
{
  "source": "shodan",
  "query": "port:11434 product:\"Ollama\"",
  "api_key_hash": "sha256:abc123...",
  "result_hash": "sha256:def456...",
  "timestamp": "2026-04-01T12:00:00Z"
}
```

## Configuration

| Config | Required | Default |
|--------|----------|---------|
| `SHODAN_API_KEY` | Yes | None |
| `SHODAN_RATE_LIMIT_RPM` | No | 60 |

## UI Display

In the Control Console, Shodan appears as:

- Strategy name: "Shodan (passive)"
- Risk tier badge: "Lowest"
- Description: "Queries Shodan API for known hosts. No direct network contact."

## See Also

- `discovery-strategies.md`: Full strategy interface
- `safety-model.md`: Risk tier definitions
- `workflow-engine.md`: How strategies fit into workflows