# UI Tactical Theme

## Status
Draft — design phase

## Philosophy

The Sintel command center should feel like an operations room, not a SaaS dashboard. The aesthetic is: high information density, clear status hierarchy, strong contrast between states, tactical efficiency.

## Color System

### Base Palette

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| bg | `#FFFFFF` | `#0a0a0a` | Page background |
| surface | `#F8F9FA` | `#111111` | Cards, panels |
| surface-alt | `#F1F3F4` | `#1a1a1a` | Nested surfaces |
| border | `rgba(0,0,0,0.1)` | `rgba(255,255,255,0.08)` | Borders, dividers |

### State Colors

| State | Color | Hex | Usage |
|-------|-------|-----|-------|
| positive | emerald | `#33d17a` | Success, healthy, online |
| warning | amber | `#ffb020` | Degraded, attention needed |
| danger | rose | `#ff5d5d` | Error, blocked, offline |
| info | sky | `#4da3ff` | Neutral active, info |

### Text Hierarchy

| Level | Light | Dark | Usage |
|-------|-------|------|-------|
| primary | `#111111` | `#ffffff` | Headings, primary text |
| secondary | `#374151` | `#9ca3af` | Secondary text, labels |
| muted | `#6b7280` | `#6b7280` | Muted, hints, timestamps |
| mono | `#111111` | `#e8f0f2` | Monospace data |

## Typography

### Font Stack

- **Headings**: Inter / Geist / Satoshi
- **Body**: Inter / system-ui
- **Monospace**: JetBrains Mono

### Scale

```css
.text-xs   /* 12px — labels, hints */
.text-sm   /* 14px — body, secondary */
.text-base /* 16px — primary body */
.text-lg   /* 18px — section headings */
.text-xl   /* 20px — page titles */
.text-2xl  /* 24px — hero headlines */
```

### Monospace for Data

All data values should use monospace:

- IP addresses
- Hostnames
- Ports
- Counts
- Timestamps (short form)
- Hash values

## Spacing

### Base Unit

4px base. Use multiples of 4.

### Common Patterns

| Use | Spacing |
|-----|---------|
| Card padding | `p-4` (16px) or `p-6` (24px) |
| Section gaps | `gap-4` or `gap-6` |
| Inline gaps | `gap-2` (8px) or `gap-3` (12px) |
| Table cells | `px-3 py-2` |

### Borders

- Border radius: `rounded-lg` (8px) for cards, `rounded-md` (6px) for inputs
- No heavy rounded corners (`rounded-xl` and above feel too "SaaS")
- Subtle borders: `border border-gray-200 dark:border-gray-800`

## Component Patterns

### Card

```
<div class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm
            dark:border-gray-800 dark:bg-gray-900">
  <!-- content -->
</div>
```

### Status Badge

```
<span class="inline-flex items-center gap-1.5 rounded-full
           px-2 py-0.5 text-xs font-mono
           bg-emerald-500/10 text-emerald-400">
  <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
  ONLINE
</span>
```

### Data Row

```
<div class="flex justify-between py-1.5 font-mono text-xs">
  <span class="text-gray-500">IP Address</span>
  <span class="text-gray-900 dark:text-gray-100">192.168.1.1</span>
</div>
```

### KPI Card

```
<div class="p-4 hover:bg-gray-800/50 transition-colors">
  <div class="flex items-center gap-2 text-green-500/70 mb-2">
    <Icon class="h-4 w-4" />
    <span class="text-xs uppercase tracking-widest font-bold">HOSTS</span>
  </div>
  <div class="text-3xl font-mono font-medium text-white">1,247</div>
  <div class="text-[10px] text-gray-500 mt-1">↑ 12% from last scan</div>
</div>
```

## Layout Patterns

### Three-Pane Command Center

```
┌─────────────┬───────────────────────────┬─────────────────┐
│ Workflow    │ Control Room              │ Evidence        │
│ Rail        │                           │ Ledger          │
│ (280px)     │ (flexible)                │ (400px)         │
└─────────────┴───────────────────────────┴─────────────────┘
```

### Split-Pane Master/Detail

```
┌────────────────────────────┬──────────────────────────────┐
│ Lead List                  │ Lead Detail                   │
│ (flexible)                 │ (flexible)                    │
└────────────────────────────┴──────────────────────────────┘
```

## Animation

### Subtle and Functional

- Transition durations: 150-200ms
- Use for:
  - Hover state changes
  - Panel open/close
  - Tab transitions
- Avoid:
  - Bouncy easing
  - Excessive motion
  - Decorative animations

### Pulsing Indicators

Use the "pulse" animation only for:

- Active status (in progress)
- Live data (streaming)

```css
.animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
```

## Responsive Behavior

| Screen | Behavior |
|--------|----------|
| Desktop (≥1280px) | All panes visible |
| Tablet (768-1279px) | Collapse right pane to tabs |
| Mobile (<768px) | Stack vertically, prioritize workflow and control |

## Dark Mode Preference

This UI is designed dark-first. Light mode is supported but the intended aesthetic is:

- Near-black backgrounds
- Subtle surface variations
- Green accent for positive states
- Monospace density for data

## Anti-Patterns

### Avoid

- Heavy drop shadows
- Many border colors
- Rounded corners on everything
- Saturated accent colors everywhere
- Large hero sections with marketing copy
- Playful illustrations or personality icons

### Prefer

- Subtle depth via surface variation
- One accent color for interactive elements
- Sharp or subtle rounding
- Accent color reserved for state and action
- Dense data presentation
- Functional iconography