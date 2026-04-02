# Hexe AI Node UI Replication Guide

This guide describes how to recreate the current Hexe AI Node frontend UI in another repository.

This is a build spec, not a design summary.

It covers:

- setup flow
- dashboard structure
- every major card and section
- theme tokens
- sizes, gaps, grids, and spacing
- refresh behavior
- API endpoints and payloads needed by the UI

Status: `Implemented`

Primary implementation files in this repository:

- `frontend/src/App.jsx`
- `frontend/src/app.css`
- `frontend/src/main.jsx`
- `frontend/src/theme/index.css`
- `frontend/src/theme/tokens.css`
- `frontend/src/theme/base.css`
- `frontend/src/theme/components.css`
- `frontend/src/theme/themes/dark.css`
- `frontend/src/theme/themes/light.css`
- `frontend/src/features/setup/*`
- `frontend/src/features/operational/*`
- `frontend/src/features/diagnostics/DiagnosticsPage.tsx`

---

## 1. Product Intent

The UI should feel like:

- an operator console
- a trusted infrastructure node control plane
- compact and status-forward
- horizontally structured on desktop
- calm, dark, and technical

The UI should not feel like:

- a consumer dashboard
- a marketing landing page
- a mobile-first stacked list on desktop
- a generic admin template

There are two primary operator modes:

1. setup flow
2. operational dashboard

There is also one focused sub-mode:

3. provider setup

---

## 2. Top-Level Runtime Behavior

The app does an immediate status load on mount, then refreshes on aligned 5-second wall-clock boundaries.

Current refresh behavior:

- immediate load when the app mounts
- then refresh at:
  - `:00`
  - `:05`
  - `:10`
  - `:15`
  - and so on

Current implementation detail:

```js
const REFRESH_INTERVAL_MS = 5000;
```

The next delay is derived from:

- current epoch milliseconds
- modulo `5000`

Replication rule:

- do not use an arbitrary `setInterval(7000)` style poll if you want parity
- snap refreshes to clock boundaries

---

## 3. Required File Structure

To recreate the UI cleanly, keep this separation:

### 3.1 App Shell / orchestration

- `frontend/src/App.jsx`

Responsibilities:

- fetch API data
- derive setup flow state
- derive dashboard props
- select the active UI mode
- wire actions to buttons

### 3.2 Theme contract

- `frontend/src/theme/tokens.css`
- `frontend/src/theme/base.css`
- `frontend/src/theme/components.css`
- `frontend/src/theme/themes/dark.css`
- `frontend/src/theme/themes/light.css`
- `frontend/src/theme/index.css`

Responsibilities:

- color tokens
- spacing tokens
- radius tokens
- theme base behavior
- shared `.card`, `.btn`, `.form-input`, `.pill` primitives

### 3.3 App-specific styling

- `frontend/src/app.css`

Responsibilities:

- layout grids
- setup shell
- operational shell
- health strip
- card-level patterns
- responsive behavior

### 3.4 Feature slices

- `frontend/src/features/setup/*`
- `frontend/src/features/operational/*`
- `frontend/src/features/diagnostics/*`

Responsibilities:

- render setup stage panels
- render dashboard cards
- render diagnostics page

---

## 4. Theme Token Contract

Use the `--sx-*` token family as the source of truth.

Current values:

```css
:root {
  --sx-bg: 222 84% 5%;
  --sx-panel: 222 50% 10%;
  --sx-border: 217 20% 20%;
  --sx-text: 210 40% 98%;
  --sx-text-muted: 215 20% 65%;
  --sx-accent: 262 83% 58%;
  --sx-success: 142 71% 45%;
  --sx-warning: 38 92% 50%;
  --sx-danger: 0 84% 60%;

  --sx-space-1: 4px;
  --sx-space-2: 8px;
  --sx-space-3: 12px;
  --sx-space-4: 16px;
  --sx-space-5: 24px;
  --sx-space-6: 32px;

  --sx-radius-sm: 6px;
  --sx-radius-md: 10px;
  --sx-radius-lg: 14px;
  --sx-radius-pill: 999px;

  --sx-shadow-1: 0 1px 2px rgba(0, 0, 0, 0.3);
  --sx-shadow-2: 0 4px 10px rgba(0, 0, 0, 0.35);

  --sx-font-sans: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
```

Compatibility aliases also exist:

- `--color-*`
- `--radius-*`
- `--shadow-*`
- `--font-sans`

Replication rule:

- new UI code should prefer `--sx-*`
- aliases are only there for compatibility with existing components

---

## 5. Global Base Styling

Current base theme behavior:

```css
:root {
  color-scheme: dark;
  font-family: var(--sx-font-sans);
  background: radial-gradient(
    circle at 20% 0%,
    hsl(var(--sx-panel)) 0%,
    hsl(var(--sx-bg)) 55%,
    hsl(var(--sx-bg)) 100%
  );
  color: hsl(var(--sx-text));
}

body {
  margin: 0;
  font-family: var(--sx-font-sans);
  background: hsl(var(--sx-bg));
  color: hsl(var(--sx-text));
}
```

Visual result:

- dark background
- subtle radial depth
- no hard page edges
- no browser default margins

Link styling:

```css
a {
  color: hsl(var(--sx-accent));
  text-decoration: none;
}
```

---

## 6. Shared Primitive Components

### 6.1 Card

```css
.card {
  background: hsl(var(--sx-panel));
  border: 1px solid hsl(var(--sx-border));
  border-radius: var(--sx-radius-md);
  padding: var(--sx-space-4);
  box-shadow: var(--sx-shadow-1);
}
```

Used for:

- app header
- setup sidebar
- setup stage cards
- setup action footer
- health strip
- overview cards
- diagnostics page

### 6.2 Button

```css
.btn {
  border-radius: var(--sx-radius-sm);
  border: 1px solid transparent;
  padding: var(--sx-space-2) var(--sx-space-3);
  cursor: pointer;
  font: inherit;
}

.btn-primary {
  background: hsl(var(--sx-accent));
  color: #fff;
}
```

Button size model:

- vertical padding: `8px`
- horizontal padding: `12px`
- compact control, not oversized CTA

### 6.3 Input

```css
.form-input {
  width: 100%;
  border: 1px solid hsl(var(--sx-border));
  border-radius: var(--sx-radius-sm);
  padding: var(--sx-space-2) var(--sx-space-3);
  background: color-mix(in oklab, hsl(var(--sx-panel)) 85%, black);
  color: hsl(var(--sx-text));
}
```

### 6.4 Pill / Badge

```css
.badge,
.pill {
  border-radius: 999px;
  padding: 2px var(--sx-space-2);
  font-size: 12px;
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-panel));
}
```

---

## 7. Outer App Layout

The full app is wrapped in:

```jsx
<div className="shell">
  <main className="app-frame">...</main>
</div>
```

### 7.1 `.shell`

```css
.shell {
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, hsl(var(--sx-accent) / 0.16), transparent 28%),
    radial-gradient(circle at 85% 15%, hsl(var(--sx-success) / 0.16), transparent 22%),
    hsl(var(--sx-bg));
}
```

Purpose:

- full-height visual surface
- ambient accent glow
- avoid a flat dark slab

### 7.2 `.app-frame`

```css
.app-frame {
  box-sizing: border-box;
  width: 90vw;
  max-width: 90vw;
  margin: 0 auto;
  padding: 24px;
}
```

Purpose:

- very wide desktop layout
- page breathing room
- not a narrow centered app shell

Responsive adjustments:

- `94vw` width at `<= 900px`
- `16px` padding at `<= 900px`
- `12px` padding at `<= 640px`

---

## 8. App Header

The app header is the compact summary block above setup or dashboard content.

Current structure:

```jsx
<section className="card app-header">
  <div className="app-header-top">...</div>
  <div className="app-header-bottom">...</div>
  <div className="app-header-meta">...</div>
</section>
```

### 8.1 Layout

```css
.app-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
  padding-top: 14px;
  padding-bottom: 14px;
}
```

### 8.2 Rows

```css
.app-header-top,
.app-header-bottom,
.app-header-meta {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
```

### 8.3 Title

```css
.app-header h1 {
  margin: 0;
  font-size: clamp(26px, 3vw, 36px);
  line-height: 1;
}
```

### 8.4 Pill and action rows

```css
.app-header-status-pills,
.app-header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
```

### 8.5 Header meta row behavior

Current behavior:

- `Updated: ...` stays on the left
- `Node: ...` is pushed to the far right

Current CSS:

```css
.app-header-meta > :last-child {
  margin-left: auto;
}
```

Current displayed fields:

- `Updated`
- `Node`

---

## 9. Setup Flow Architecture

The setup flow is the non-dashboard operator path.

It uses:

- left sticky setup sidebar
- right-column summary and active-stage content
- bottom action footer

Current top-level layout:

```jsx
<section className="app-shell">
  <aside className="card stack flow-sidebar">...</aside>
  <div className="main-column">
    <section className="content-stack">
      ...
      <footer className="card setup-shell-footer">...</footer>
    </section>
  </div>
</section>
```

### 9.1 Setup shell grid

```css
.app-shell {
  display: grid;
  grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}
```

### 9.2 Stack helpers

```css
.main-column,
.content-stack,
.setup-main-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
```

### 9.3 Setup sidebar

```css
.flow-sidebar {
  position: sticky;
  top: 24px;
}
```

### 9.4 Shared heading style

```css
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.section-heading h2 {
  margin: 0;
  font-size: 20px;
}
```

---

## 10. Setup Sidebar Stepper

The setup sidebar lists stages only.

It is intentionally compact.

Current structure:

```jsx
<aside className="card stack flow-sidebar">
  <div className="section-heading">
    <h2>Setup Flow</h2>
    <span className="pill">{activeStageLabel}</span>
  </div>
  <nav className="flow-steps">...</nav>
</aside>
```

### 10.1 Step list

```css
.flow-steps {
  display: grid;
  gap: 10px;
}
```

### 10.2 Step card

```css
.flow-step {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--sx-radius-md);
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-text) / 0.03);
  position: relative;
}
```

### 10.3 Step marker

```css
.flow-step-marker,
.flow-step-index {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  font-weight: 700;
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-panel));
}
```

### 10.4 Completed check

```css
.flow-step-check {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
  color: hsl(var(--sx-panel));
  background: hsl(var(--sx-success));
}
```

### 10.5 Step state styling

Current warning styles:

- current stage
- in-progress stage

Current success styles:

- completed stages

Current error styles:

- failed/error stages

State colors:

- success: `--sx-success`
- warning: `--sx-warning`
- error: `--sx-danger`

---

## 11. Setup Stage Order

The current AI node setup flow stages are:

1. `core_connection`
2. `bootstrap_discovery`
3. `registration`
4. `approval`
5. `trust_activation`
6. `provider_setup`
7. `capability_declaration`
8. `governance_sync`
9. `ready`

The active panel is selected in `renderSetupActivePanel()`.

The setup action footer is selected in `buildSetupActions()`.

---

## 12. Setup Summary Header Card

This is the top summary card on the right side of setup mode.

Current content:

- title
- subtitle
- summary pills

Current summary pill fields:

- `Lifecycle`
- `Trust`
- `Governance`
- `Core`

### 12.1 Summary pill styling

```css
.setup-shell-summary-pills {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.setup-shell-summary-pill {
  min-width: 170px;
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: var(--sx-radius-md);
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-text) / 0.03);
}
```

---

## 13. Setup Active Stage Card

This card shows only the content for the current stage.

Current structure:

```jsx
<article className="card setup-shell-main-card">
  <CardHeader title={activeStageLabel} subtitle="Only the information and actions for the current stage are shown here." />
  <div className="setup-shell-panel">{activePanel}</div>
</article>
```

Card gap:

- `24px` between stacked blocks

Panel gap:

- `24px` between panel internals

---

## 14. Setup Action Footer

The setup footer sits below the active stage card.

It can show up to three grouped regions:

1. current step
2. more actions
3. reset and recovery

Current group labels:

- `Current Step`
- `More Actions`
- `Reset & Recovery`

Current styling:

```css
.setup-shell-footer {
  display: grid;
  gap: 12px;
}

.setup-shell-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.setup-shell-action-label {
  min-width: 120px;
  color: hsl(var(--sx-text-muted));
  font-size: 0.82rem;
}
```

---

## 15. Setup Stage Cards And Content

Each setup stage panel uses:

- explanatory muted paragraph
- `state-grid`
- optional warnings or blocking lists
- optional embedded provider form

### 15.1 Core Connection / Bootstrap Discovery

Component:

- `SetupCoreConnectionPanel`

Purpose:

- show bootstrap host
- show lifecycle
- show node id

Fields:

- `Bootstrap Host`
- `Lifecycle`
- `Node ID`

### 15.2 Registration

Component:

- `SetupRegistrationPanel`

Purpose:

- explain that Hexe Core discovery finished
- explain registration is waiting for approval session creation

Fields:

- `Node ID`
- `Status`

### 15.3 Approval

Component:

- `SetupApprovalPanel`

Purpose:

- explain that Hexe Core operator approval is required

Fields:

- `Node ID`
- `Approval Link`

### 15.4 Trust Activation

Component:

- `SetupTrustActivationPanel`

Purpose:

- show trusted runtime validation state

Fields:

- `Trust Status`
- `Startup Mode`
- `Paired Hexe Core`

### 15.5 Provider Setup

Component:

- `SetupProviderPanel`

Purpose:

- explain AI provider setup before declaration
- show current provider and task-family readiness

Fields:

- `OpenAI Enabled`
- `OpenAI Budget`
- `Task Families`
- `Provider Ready`
- `Task Selection`

This panel can contain:

- inline provider-selection form
- or the dedicated provider setup page content

### 15.6 Capability Declaration

Component:

- `SetupCapabilityDeclarationPanel`

Purpose:

- explain blockers before declaration
- show readiness matrix

Fields:

- `Declare Ready`
- `Trust Ready`
- `Identity Ready`
- `Runtime Context`
- `Model Readiness`

Optional blocking list:

- rendered when `setupBlockingReasons` is non-empty

### 15.7 Governance Sync

Component:

- `SetupGovernancePanel`

Purpose:

- show governance freshness before final handoff

Fields:

- `Governance`
- `Policy Version`
- `Declaration Timestamp`

### 15.8 Ready

Component:

- `SetupReadyPanel`

Purpose:

- confirm setup completion
- keep setup reopenable

Fields:

- `Lifecycle`
- `Hexe Core`
- `Governance`

---

## 16. Provider Setup View

The provider setup UI is a dedicated sub-view, not a dashboard card.

Current provider route intent:

- `#/setup/provider/openai`

Current page content:

- provider enable toggle
- provider budget form
- credentials form
- model refresh / reload controls
- model selection grid
- enabled-model toggles
- pricing modal entrypoints

Current form topics:

- provider enabled
- budget cents
- budget period
- OpenAI API token
- project name
- selected default / allowed models

This page uses:

- `.setup-form`
- `.state-grid`
- `.mini-card-grid`
- `.model-card`
- `.capability-badge`

Replication rule:

- keep provider setup task-focused and separate from the dashboard overview

---

## 17. Operational Dashboard Architecture

The operational dashboard has three layers:

1. compact app header
2. left-side section nav + right-side content shell
3. content header strip + section cards

Current shell:

```jsx
<section className="operational-shell">
  <aside className="card operational-shell-nav-card">...</aside>
  <div className="operational-shell-content">
    <article className="card node-health-strip operational-content-header">...</article>
    <section className="grid operational-dashboard-grid">...</section>
  </div>
</section>
```

### 17.1 Shell grid

```css
.operational-shell {
  display: grid;
  grid-template-columns: minmax(220px, 260px) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}
```

### 17.2 Content stack

```css
.operational-shell-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
}
```

### 17.3 Sticky nav

```css
.operational-shell-nav-card {
  position: sticky;
  top: 24px;
}
```

### 17.4 Dashboard grid

```css
.operational-dashboard-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: start;
}
```

---

## 18. Operational Navigation

Current sections:

1. `Overview`
2. `Capabilities`
3. `Runtime`
4. `Activity`
5. `Diagnostics`

Buttons are vertically stacked and full width.

Current CSS:

```css
.operational-shell-nav {
  display: grid;
  gap: 10px;
}

.operational-nav-btn {
  width: 100%;
  justify-content: center;
}
```

---

## 19. Health Strip

The health strip is the first content block inside the operational shell.

It is not a footer and not a side card.

Current metric set:

1. `Lifecycle`
2. `Trust`
3. `Core API`
4. `MQTT`
5. `Governance`
6. `Providers`
7. `Last Heartbeat`

### 19.1 Strip card

```css
.node-health-strip {
  padding: 18px 20px;
}
```

### 19.2 Inner grid

```css
.node-health-strip-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 14px;
}
```

### 19.3 Metric tile

```css
.node-health-strip-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: var(--sx-radius-md);
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-text) / 0.03);
}
```

### 19.4 Label styling

Use:

- `.muted`
- `.tiny`

### 19.5 Value styling

Use:

- `StatusBadge`
- `HealthIndicator`
- `<code>`

### 19.6 Last Heartbeat behavior

Current display rule:

- label is `Last Heartbeat`
- value is a relative age string

Examples:

- `0 sec ago`
- `20 sec ago`
- `4 min ago`
- `1 hour ago`

It does not show a raw localized timestamp in the strip.

---

## 20. Status And Indicator Styling

### 20.1 Utility text

```css
.muted {
  color: hsl(var(--sx-text-muted));
}

.tiny {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
```

### 20.2 Severity indicator

```css
.severity-indicator {
  display: inline-flex;
  align-items: center;
}

.severity-success {
  color: hsl(var(--sx-success));
}

.severity-warning {
  color: hsl(var(--sx-warning));
}

.severity-danger {
  color: hsl(var(--sx-danger));
}

.severity-meta {
  color: hsl(var(--sx-accent));
}
```

### 20.3 Status badge / health indicator

```css
.status-badge,
.health-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 7px 10px;
  border-radius: var(--sx-radius-pill);
  border: 1px solid currentColor;
  text-transform: capitalize;
  font-size: 13px;
  line-height: 1;
  background: hsl(var(--sx-panel));
}
```

### 20.4 Dot

```css
.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}
```

---

## 21. Overview Section Cards

The `Overview` section currently renders up to four cards:

1. degraded banner, conditionally
2. `Node Overview`
3. `Core Connection`
4. `Actions`

### 21.1 Degraded Banner

Component:

- `DegradedStateBanner`

Purpose:

- keep degraded nodes inside dashboard mode
- avoid bouncing users back to setup

Contents:

- title: `Operational With Warnings`
- muted explanation
- warning reason line
- action buttons

### 21.2 Node Overview Card

Component:

- `NodeOverviewCard`

Subtitle:

- `Primary home for identity, lifecycle, and trusted pairing summary.`

Fields:

- `Node ID`
- `Node Name`
- `Lifecycle`
- `Trust`
- `Paired Hexe Core`
- `Software`
- `Pairing Timestamp`

Important display rule:

- `Pairing Timestamp` is rendered in local time

### 21.3 Core Connection Card

Subtitle:

- `Trusted Core endpoint metadata and current onboarding linkage.`

Fields:

- `Core ID`
- `Core API`
- `Operational MQTT`
- `Connection`
- `Onboarding Ref`
- `Telemetry Freshness`
- `Telemetry Age`

Important behavior:

- `Operational MQTT` shows `host:port` when available
- if endpoint string is missing but connection is healthy, display `connected`
- `Onboarding Ref` is masked as `**********xxxxxxx`
- `Telemetry Freshness` is rendered as a health indicator
- `Telemetry Age` is rendered as:
  - `20s`
  - `4m`
  - `1h`
  - `2d`

Current freshness thresholds:

- `fresh` at `<= 300s`
- `stale` at `<= 1800s`
- `inactive` above `1800s`
- `offline` if the connection is down
- `unknown` if there is no heartbeat timestamp

### 21.4 Actions Card

Component:

- `OperationalActionsCard`

Subtitle:

- `Operational controls are grouped by purpose so routine actions stay separate from diagnostics and admin tools.`

Current action groups:

1. `Configuration`
2. `Runtime Controls`
3. `Admin & Diagnostics`

Current configuration actions:

- `Open Setup`
- `Configure OpenAI Provider`
- `Refresh Governance`
- `Refresh Provider Models`
- `Redeclare Capabilities`

Current runtime actions:

- `Restart Backend`
- `Restart Frontend`
- `Restart Node`

Current admin action:

- `Open Diagnostics`

---

## 22. Capabilities Section Cards

The `Capabilities` section currently renders:

1. `Capability Summary`
2. `Resolved Tasks`

### 22.1 Capability Summary Card

Subtitle:

- `Primary home for provider, model, and feature resolution.`

Primary CTA:

- `Setup AI Provider`

Displayed groups:

- `Enabled Providers`
- `Usable Models`
- `Blocked Models`
- `Resolved Features`

Metadata fields:

- `Resolved Task Families`
- `Classifier Source`
- `Capability Graph Version`

This card uses:

- `CompactChipList`
- `capability-summary-layout`
- `capability-summary-block`
- `state-grid`

### 22.2 Resolved Tasks Card

Subtitle:

- `Grouped capability families for operational readability.`

Behavior:

- groups resolved tasks by category
- displays task chips
- allows expanding long categories with `Show More` / `Show Less`

---

## 23. Runtime Section Cards

The `Runtime` section currently renders:

1. `Runtime Health`
2. `Runtime Services`
3. `Actions`

### 23.1 Runtime Health Card

Subtitle:

- `Runtime-only health signals live here instead of repeating across overview cards.`

Fields:

- `Core API`
- `Operational MQTT`
- `Governance`
- `Last Telemetry`
- `Node Health`

Note:

- the runtime detail card still uses `Last Telemetry`
- the health strip uses `Last Heartbeat`

### 23.2 Runtime Services Card

Subtitle:

- `Primary home for backend, frontend, and node service state.`

Fields:

- `Backend`
- `Frontend`
- `Node`

### 23.3 Shared Actions Card

The same `Actions` card component from Overview is reused here.

---

## 24. Activity Section Cards

The `Activity` section currently renders:

1. `Onboarding`
2. `Recent Activity`

### 24.1 Onboarding Card

Subtitle:

- `Live onboarding progress by lifecycle stage.`

Current onboarding steps shown:

- `Bootstrap Discovery`
- `Registration`
- `Approval`
- `Trust Activation`

Optional extra line:

- `Pending approval for node: ...`

### 24.2 Recent Activity Card

Subtitle:

- normal mode:
  - `Recent node events and timestamps.`
- degraded mode:
  - `Recent events are shown while the node remains available in degraded mode.`

Current activity items:

- `Last declaration`
- `Governance status`
- `Provider intelligence refresh`
- `Last declaration result`
- `Current warning/error`

Each row contains:

- label
- optional hint
- severity-colored value

---

## 25. Diagnostics Section

The `Diagnostics` section renders a single large diagnostics card with collapsible subsections.

Main title:

- `Diagnostics`

Subtitle:

- `Advanced inspection and admin controls live here instead of the main dashboard.`

Current subsections:

1. `Capability Diagnostics`
2. `Declaration Payload / Result`
3. `Feature Catalog`
4. `Pricing Catalog`
5. `Pricing Diagnostics`
6. `Capability Graph`
7. `Admin Actions`
8. `Session Diagnostics`

### 25.1 Admin Actions subsection

Grouped into:

- `Sync & Refresh`
- `Advanced Maintenance`

Current admin action buttons:

- `Refresh Provider Models`
- `Redeclare Capabilities To Core`
- `Recompute Deterministic Catalog`
- `Recompute Capability Graph`

### 25.2 Session Diagnostics subsection

Fields:

- `Lifecycle`
- `Last Update`
- `Partial Failures`

Button:

- `Copy Diagnostics`

---

## 26. Common Card And Grid Patterns

### 26.1 Card header

```css
.card-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 18px;
}
```

### 26.2 State grid

```css
.state-grid {
  display: grid;
  grid-template-columns: minmax(120px, 180px) minmax(0, 1fr);
  gap: 12px 16px;
  align-items: center;
}
```

Use this for:

- key/value detail cards
- setup state summaries
- runtime detail panels

### 26.3 Generic grid

```css
.grid {
  display: grid;
  gap: 24px;
}
```

### 26.4 Two-column facts grid

```css
.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 20px;
  margin: 0;
}
```

### 26.5 Action group panel

```css
.action-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: var(--sx-radius-md);
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-text) / 0.03);
}
```

### 26.6 Chip list

Used for:

- providers
- models
- resolved tasks
- features

Visual style:

- rounded pills
- compact spacing
- wrap naturally

---

## 27. Forms And Inputs

### 27.1 Setup form grid

```css
.setup-form {
  display: grid;
  gap: 12px;
}
```

### 27.2 Labels / fields

```css
.setup-form label,
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 14px;
}
```

### 27.3 Standard field label

```css
.field-label {
  color: hsl(var(--sx-text-muted));
  font-size: 14px;
}
```

### 27.4 Toggle field

```css
.toggle-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border-radius: var(--sx-radius-md);
  border: 1px solid hsl(var(--sx-border));
  background: hsl(var(--sx-text) / 0.03);
}
```

### 27.5 Textarea

```css
.form-textarea {
  min-height: 132px;
  resize: vertical;
}
```

---

## 28. Responsive Behavior

Primary responsive breakpoint:

- `900px`

Current rules at `<= 900px`:

- `app-frame` becomes `94vw`
- setup shell becomes one column
- operational shell becomes one column
- generic grid becomes one column
- operational dashboard grid becomes one column
- sticky sidebars stop being sticky
- health strip goes from 7 columns to 2
- facts go to one column
- state-grid goes to one column

Current rules at `<= 640px`:

- page padding becomes `12px`
- model grids collapse to one column
- capability toggle grid becomes one column
- health strip becomes one column
- stacked rows like activity/model header rows become vertical
- buttons in rows become full width

Replication rule:

- do not preserve the seven-column strip on mobile

---

## 29. Required API Endpoints

The current UI expects the following backend endpoints.

### 29.1 Status and baseline data

- `GET /api/node/status`
- `GET /api/governance/status`
- `GET /api/providers/config`
- `GET /api/providers/openai/credentials`
- `GET /api/providers/openai/models/catalog`
- `GET /api/providers/openai/models/capabilities`
- `GET /api/providers/openai/models/features`
- `GET /api/providers/openai/models/enabled`
- `GET /api/providers/openai/models/latest?limit=...`
- `GET /api/providers/openai/capability-resolution`
- `GET /api/capabilities/node/resolved`
- `GET /api/capabilities/config`
- `GET /api/services/status`
- `GET /api/budgets/state`
- `GET /api/capabilities/diagnostics` (admin)

### 29.2 Setup / onboarding actions

- `POST /api/onboarding/initiate`
- `POST /api/onboarding/restart`

### 29.3 Provider and capability configuration

- `POST /api/providers/openai/preferences`
- `POST /api/providers/openai/models/enabled`
- `POST /api/capabilities/config`
- `POST /api/providers/config`
- `POST /api/providers/openai/credentials`

### 29.4 Governance / runtime controls

- `POST /api/governance/refresh`
- `POST /api/services/restart`
- `POST /api/capabilities/declare`
- `POST /api/capabilities/redeclare` (admin)
- `POST /api/capabilities/providers/refresh`

### 29.5 Pricing and catalog maintenance

- `POST /api/providers/openai/pricing/manual`
- `POST /api/providers/openai/models/classification/refresh`
- `POST /api/capabilities/rebuild`

---

## 30. Required Data Fields

The UI needs these broad data shapes.

### 30.1 Lifecycle / onboarding

Needed for setup flow and header:

- `status`
- `pending_approval_url`
- `node_id`
- `pending_session_id`
- `startup_mode`

### 30.2 Trusted runtime context

Needed for overview and Core Connection:

- `paired_core_id`
- `core_api_endpoint`
- `operational_mqtt_host`
- `operational_mqtt_port`
- `pairing_timestamp`

### 30.3 Runtime health

Needed for health strip and runtime cards:

- governance freshness
- last heartbeat/telemetry timestamp
- operational MQTT readiness / connection state
- lifecycle-derived node health state

### 30.4 Capability summary

Needed for setup and capabilities section:

- enabled providers
- selected task families
- accepted declaration timestamp
- governance policy version
- setup readiness flags
- blocking reasons
- declaration allowed

### 30.5 Provider and model data

Needed for provider setup and capability cards:

- provider enabled state
- provider budget limits
- selected model ids
- enabled model ids
- discovered model catalog
- model capability entries
- model feature entries
- usable models
- blocked models

### 30.6 Diagnostics

Needed for diagnostics page:

- discovered models
- enabled models
- resolved tasks
- capability graph version
- last declaration payload
- last declaration result
- feature catalog
- pricing catalog
- pricing diagnostics
- provider intelligence refresh timestamp
- last error

---

## 31. Copy And Interaction Rules

Keep the UI copy:

- compact
- operational
- direct
- infrastructure-oriented

Interaction rules:

- setup stays available after readiness
- provider config is separated from dashboard clutter
- diagnostics are hidden behind a dedicated section
- degraded nodes stay in dashboard mode
- dangerous or advanced maintenance actions stay out of default overview cards

---

## 32. Rebuild Checklist

If recreating this UI from scratch:

1. Implement the theme token layer first.
2. Implement `.card`, `.btn`, `.form-input`, `.pill`.
3. Implement `shell` and `app-frame`.
4. Build the app header.
5. Build the setup shell with sticky sidebar.
6. Build the setup stage panels in the current stage order.
7. Build the provider setup sub-view.
8. Build the operational shell with left nav.
9. Build the 7-column health strip.
10. Build overview cards.
11. Build capability cards.
12. Build runtime cards.
13. Build activity cards.
14. Build diagnostics page.
15. Add aligned 5-second refresh scheduling.
16. Confirm responsive collapse at `900px` and `640px`.

---

## 33. Bottom Line

To reproduce this UI accurately, you need more than a dark theme.

You must recreate:

- the two-mode architecture
- the sticky setup flow
- the dedicated provider setup page
- the left-nav operational shell
- the 7-slot health strip
- the compact card-header and state-grid language
- the action grouping model
- the diagnostics isolation model
- the aligned 5-second refresh behavior
- the API payloads that drive setup, health, capabilities, and diagnostics

That combination is what makes the current Hexe AI Node UI look and behave the way it does.
