---
name: flow-applicator
description: Flow-graph based job application automation. Reads jobs from auto-job-hunt, detects ATS platforms, replays known flows, learns from deviations. Minimizes token cost by storing field mappings, questions, and navigation in reusable JSON flow graphs.
---

# Flow Applicator

## Overview

Automates job applications using reusable **flow graphs** — JSON-based state machines that map each ATS platform's screens, fields, questions, and navigation. Known flows are replayed with zero LLM cost; only deviations trigger snapshot analysis.

## When to Use

- User says "apply to jobs", "run applications", "submit applications"
- User has a `jobs.md` file from `auto-job-hunt` with scored jobs
- User wants to apply to Dice/LinkedIn/Greenhouse/Lever/Ashby/Workday jobs

## When NOT to Use

- User wants to scrape jobs (use `auto-job-hunt` or `job-application-scraper`)
- User wants to manually review each application before submit
- Jobs require login-gated portals the agent can't access

## Architecture

```
jobs.md → parse → dedup check → platform detect → load flow → fill fields → navigate → submit
                                                       ↑                         |
                                                  flow_builder ← snapshot ← deviation?
```

### Key Directories

| Path | Purpose | Scope |
|------|---------|-------|
| `{repo}/.agents/skills/flow-applicator/flows/` | Flow JSON files + registry | Global (shared) |
| `{workspace}/skills/flow-applicator/scripts/` | Python modules | Workspace |
| `{workspace}/skills/flow-applicator/instincts/` | Learned patterns | Workspace |
| `{workspace}/skills/flow-applicator/prompts/` | Sub-agent prompts | Workspace |
| `{workspace}/applications/` | Application results + index | Workspace |

### Modules

| Module | Purpose |
|--------|---------|
| `paths.py` | Dynamic path resolution (repo root, workspace, flows, applications) |
| `flow_engine.py` | FlowGraph/FlowNode/FlowEdge dataclasses + FlowRegistry |
| `answer_engine.py` | Priority-based answer resolution (5-level chain) |
| `dedup_checker.py` | Duplicate detection via `_index.json` (job ID + URL + company/title) |
| `status_tracker.py` | Per-application result logging with timing and token tracking |
| `flow_builder.py` | Parse snapshots → structured page data, match/build flow nodes, login detection |
| `orchestrator.py` | Main entry: parse jobs, plan, execute loop, login handling, Dice-specific processing |

## Workflow

### Phase 1: Parse & Plan

```python
from scripts.orchestrator import create_session_plan

plan = create_session_plan(
    jobs_path=Path("jobs/2026-04-07/2026-04-07_19-27-27/jobs.md"),
    min_score=70,
    max_applications=10,
)
# Returns: jobs list, dedup results, platform detection, flow matches
```

The agent should print the plan summary and ask the user to confirm before applying.

### Phase 2: Navigate & Detect Platform

For Dice URLs (which redirect to the real ATS):

1. Navigate to the Dice apply URL
2. Follow the redirect to the actual ATS
3. Detect the platform from the final URL using `FlowRegistry.detect_platform()`
4. Load the matching flow graph

### Phase 3: Execute Flow

For each page in the application:

1. Take a `browser_snapshot` (NOT screenshot)
2. Call `process_page(ctx, snapshot_text, url)` to get actions
3. Execute each action via Playwright MCP:
   - `fill` → `playwright_browser_fill_form` or `playwright_browser_type`
   - `select` → `playwright_browser_select_option`
   - `check` → `playwright_browser_click`
   - `upload` → `playwright_browser_file_upload`
   - `click` → `playwright_browser_click`
   - `need_answer` → use LLM to generate, then add to flow
4. After filling all fields, click next/submit
5. Repeat until done or error

### Phase 4: Handle Deviations

When `process_page()` returns `need_answer` actions:

1. The agent generates an answer using context (job description + profile)
2. If the question is generic (applies to all jobs), add to flow `commonQuestions`
3. If company-specific, add to the application result only
4. If a whole new page appeared, create a sister node via `flow_builder`

### Phase 5: Track & Report

After each application:
- Record in `applications/_index.json` (dedup for future runs)
- Save detailed result to `applications/{date}/{job_id}.json`
- Update flow graph if new questions/fields were learned

After the session:
- Save `_summary.json` with aggregate stats
- Report to user: submitted / failed / skipped / new patterns learned

## Answer Resolution Priority

1. **Flow commonQuestions** — stored Q&A in the platform flow (cheapest)
2. **question_templates.md** — pattern-matched from `references/` (free)
3. **role_qna.md** — role-specific Q&A (free)
4. **profile_data.md** — structured YAML profile fields (free)
5. **LLM-generated** — last resort (costs tokens; result cached to flow)

## Flow Graph Format

```json
{
  "flowId": "greenhouse",
  "version": "1.0.0",
  "platform": "greenhouse",
  "platformType": "ats",
  "description": "Greenhouse ATS application form",
  "nodes": {
    "landing": { "type": "page", "urlPattern": "...", "fields": [...] },
    "form_start": { "type": "form", "fields": [...], "nextButton": "..." }
  },
  "edges": [
    { "from": "landing", "to": "form_start", "trigger": "click_apply" }
  ],
  "fieldMappings": { "firstName": { "source": "profile", "field": "name" } },
  "commonQuestions": [
    { "question": "Are you authorized to work in the US?", "answer": "Yes" }
  ],
  "knownFields": { "firstName": { "type": "text", "required": true } }
}
```

## Sister Nodes

When a deviation occurs on an existing node, do NOT replace the node. Instead:

```json
{
  "form_page_2": {
    "type": "form",
    "fields": ["experienceYears", "currentTitle"],
    "sisters": [
      {
        "id": "form_page_2_v2",
        "condition": "has_field:salaryExpectation",
        "node": { "type": "form", "fields": ["experienceYears", "currentTitle", "salaryExpectation"] }
      }
    ]
  }
}
```

## Supported Platforms

| Platform | Flow ID | Status |
|----------|---------|--------|
| LinkedIn Easy Apply | `linkedin_easy_apply` | Seed flow |
| Greenhouse | `greenhouse` | Seed flow |
| Lever | `lever` | Seed flow |
| Ashby | `ashby` | Seed flow |
| Workday | `workday` | Seed flow |
| Dice (redirect) | N/A | Navigates to real ATS |

## Commands

### Apply to today's jobs
```
Apply to the qualified jobs from today's job search. Use the flow-applicator skill.
```

### Apply to specific date
```
Apply to jobs from 2026-04-07 using flow-applicator. Min score 80%.
```

### Dry run (plan only)
```
Show me the application plan for today's jobs. Don't apply yet.
```

### Check application history
```
Show my application history and stats.
```

## Error Handling

| Scenario | Action |
|----------|--------|
| Login required | Record as "skipped — login required" |
| CAPTCHA | Record as "skipped — CAPTCHA" |
| Rate limited | Stop session, record remaining as "deferred" |
| Form validation error | Retry with corrected value, then fail if persists |
| Page timeout | Retry once, then skip |
| Unknown platform | Take snapshot, attempt generic form fill, record deviations |

## Token Cost Model

| Action | Token Cost | Frequency |
|--------|-----------|-----------|
| Parse jobs.md | ~0 (Python) | Once per session |
| Dedup check | ~0 (Python) | Once per job |
| Known flow replay | ~500 (snapshot parse) | Per page |
| New question (LLM) | ~2000 | Per unknown question |
| Full page discovery | ~5000 | Only for unknown platforms |

Target: **< 3000 tokens per known-platform application** (vs. ~15000+ for full LLM-driven fill).
