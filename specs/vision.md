# Sintel — Signals Intelligence Command Center

## Status
Draft — design phase

## Vision

Sintel is a proactive defense command center built around infrastructure signals intelligence.

Its mission: **identify threats to our community before they manifest, and prevent bad things from happening.**

Sintel collects, verifies, enriches, and graph-connects public infrastructure signals — with a specific initial focus on exposed inference infrastructure (Ollama and adjacent services). But the architecture is designed to handle any discoverable public-facing service family.

Sintel is **not** a port scanner. It is a governed signals system where port scanning is one discovery strategy among several, each with different risk profiles and different trust levels.

## Core Principles

### 1. Passiveness-first, activeness constrained

Every strategy starts passive. Active verification only happens under explicit policy constraints and operator awareness.

### 2. Exclusions are constitutional

All strategies use the same merged exclusion layer. If exclusions are missing or empty, nothing runs. This is not optional and is not overridable by automation.

### 3. Provenance is non-negotiable

Every observation carries its full source chain:
- who triggered it
- what strategy produced it
- what targets were queried
- what exclusions were in effect
- what workflow it belongs to
- what time it happened

### 4. The workflow is the operator-facing unit

Operators don't "start a scan". They start or inspect **workflows**. Jobs are internal implementation.

### 5. Integration over isolation

Sintel feeds into and receives signals from:
- Graph Weaver
- Threat Radar
- eta-mu orchestration
- `shuvcrawl` and other crawlers
- public intelligence feeds

Sintel is one collector in a larger defense system.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Sintel Command Center                    │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │   Workflows   │  │    Map       │  │    Graph View          │ │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────────┘ │
│         │                  │                    │                │
│  ┌──────┴──────────────────┴────────────────────┴──────────────┐ │
│  │                   Operator Control Surface                   │ │
│  │    Groups │ Filters │ Policies │ Actions │ Evidence           │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                       │
│  ┌────────────────────────┴────────────────────────────────────┐ │
│  │                   Discovery Strategies                      │ │
│  │  Passive │ Active Bounded │ Active Unrestricted               │ │
│  │  Shodan  │ Tor Connect    │ Masscan                           │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                       │
│  ┌────────────────────────┴────────────────────────────────────┐ │
│  │                   Workflow Engine                            │ │
│  │  discover → ingest → verify → geocode → graph-emit →         │ │
│  │  classify → alert                                            │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                       │
│  ┌────────────────────────┴────────────────────────────────────┐ │
│  │                   Observation Store                          │ │
│  │  Append-only evidence │ Groups │ Rules │ Provenance           │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

External integrations:

  ┌──────────┐  ┌────────────┐  ┌───────────┐  ┌──────────────┐
  │ Graph    │  │ Threat     │  │ eta-mu    │  │ shuvcrawl    │
  │ Weaver   │  │ Radar      │  │           │  │              │
  └──────────┘  └────────────┘  └───────────┘  └──────────────┘
```

## Discovery Strategies

All discovery strategies are part of the same interface: they produce a set of host-level observations given a target and exclusions. They differ in trust, blast radius, and active-passiveness.

| Strategy     | Type       | Risk   | Requires | Output                    |
|--------------|------------|--------|----------|---------------------------|
| `shodan`     | Passive    | Low    | API key  | hosts from Shodan search  |
| `tor-connect`| Bounded    | Medium | Tor stack| hosts that respond on port|
| `masscan`    | Unrestricted| High  | Direct egress | hosts with open ports |

See `specs/discovery-strategies.md` for the full strategy contract.

## Observations

An observation is an append-only evidence record. Observations are the atomic unit that feeds the graph.

See `specs/observation-schema.md` for the schema contract.

## Entities and Graph

Entities are the graph nodes. Sintel observes hosts, blocks, ASNs, orgs, and countries. It also owns groups, workflows, and policies as first-class entities.

See `specs/entity-graph-contract.md` for the graph integration contract.

## Workflows

A workflow is the full chain of a discovery cycle. Workflows are the primary unit operators interact with.

See `specs/workflow-engine.md` for the workflow contract.

## Policies

Policies are the safety governance layer. They define what is allowed, what is blocked, and what triggers alerts.

See `specs/policy-engine.md` for the policy contract.

## Command Center UI

The command center is a six-surface layout.

See `specs/command-center-ui.md` for the UI contract.

## Safety Model

See `specs/safety-model.md` for the safety contract, including:
- exclusion constitutional model
- strategy risk tiers
- operator accountability
- provenance requirements
- blast radius controls
