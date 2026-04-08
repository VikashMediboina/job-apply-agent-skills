---
name: auto-job-hunt
description: Automated job scraping from Dice and Indeed MCPs with role-specific search terms, scoring, and filtering. Use when user wants to find jobs matching their profile with configurable filters.
---

# Auto Job Hunt

## Overview

This skill automates job searching by scraping Dice and Indeed job boards using their MCP integrations. It uses role-specific search terms, applies scoring criteria to filter jobs based on user profile fit, and generates a consolidated set of markdown files organized by role, source, and recommendation.

## When to Use

- User wants to find jobs matching their profile (requires prior profile setup via `resume-profile-generator`)
- User specifies a role and quantity (e.g., "Get 50 jobs for AI/ML Engineer")
- User wants configurable filters: location, visa status, work mode, score threshold
- User wants jobs from multiple sources (Dice + Indeed) with parallel execution

## When NOT to Use

- User has no profile setup (run `resume-profile-generator` first)
- User wants only one job board (use MCP directly)
- User wants manual job search without scoring

---

## Workflow

### Phase 1: Validation

1. **Load ask-questions-if-underspecified skill** for clarifying user intent
2. **Validate profile bundle exists**: `{repo_root}/{username}/{role}/generation.md`
3. **Validate MCPs connected**: Test Dice Job Search + Indeed Job Search

If validation fails:
- Profile not found → Ask user to run `resume-profile-generator` first
- MCPs not connected → Show setup guide with links

### Phase 2: Request Parsing

Parse user request to extract:

| Parameter | Type | Default |
|-----------|------|---------|
| `roles` | string | Required |
| `quantity` | integer | Required |
| `timeline` | string | "24hrs" |
| `location` | string | Profile default |
| `visa_status` | string | Profile default |
| `visa_required` | boolean | Profile default |
| `work_mode` | string | "Flexible" |
| `score_threshold` | number | 50 |
| `source_split` | string | "50/50" |

### Phase 3: Planning

1. **Role split**: If multiple roles → split quantity evenly (or ask user)
2. **Source split**: Use 50/50 default or user-specified (e.g., "60/40")
3. **Search terms selection**: Read from `{role}/searchterms.md`, select 2-4 per source (prioritize Set 2 + Set 3)

### Phase 4: Execution

Hierarchy: **Role Subagent** → **Source Subagents** (Dice + Indeed) → **Search Term Subagents** (2-4 each)

Each search term subagent:
1. Uses MCP to scrape jobs
2. Applies scoring criteria from `{role}/scoring.md`
3. Saves to `{workspace_root}/temp/{source}/{role}/scored/{search_term}.md`

### Phase 5: Aggregation & Filtering

1. Source subagent aggregates all scored jobs from its search terms
2. Role subagent aggregates Dice + Indeed results
3. Apply user filters + score threshold
4. If total < requested → note shortfall

### Phase 6: Output

1. Generate markdown files with proper segregation:
   - `{repo_root}/jobs/{date}/{timestamp}/jobs.md` - All jobs (Apply + Consider segregated)
   - `{repo_root}/jobs/{date}/{timestamp}/index.md` - Summary index
2. Write status: `{repo_root}/jobs/status/{date}/{timestamp}.md`
3. Cleanup: Remove `{workspace_root}/temp/` directory
4. Return summary to user

---

## Sub-agents

### Role Subagent

**Purpose**: Orchestrate job search for a single role

**Inputs**:
- role name
- quantity
- user filters (location, visa, work_mode)
- source split
- search terms per source

**Outputs**:
- Aggregated scored jobs from all sources
- Filtered by score threshold

### Source Subagent

**Purpose**: Search one job board (Dice or Indeed)

**Inputs**:
- source name (dice/indeed)
- role name
- search terms (2-4)
- quantity per term
- scoring criteria
- user filters

**Outputs**:
- Aggregated scored jobs from all search terms
- Saved to `{workspace_root}/temp/{source}/{role}/jobs.md`

### Search Term Subagent

**Purpose**: Execute search for one search term

**Inputs**:
- search term string
- source (dice/indeed)
- role name
- quantity to fetch
- scoring criteria path
- profile path
- user filters

**Outputs**:
- Scored jobs (score 0-100, recommendation, red_flags)
- Saved to `{workspace_root}/temp/{source}/{role}/scored/{search_term}.md`

---

## Scoring

### Score Calculation

Load from `{role}/scoring.md`:

| Category | Weight |
|----------|--------|
| User-Level Fit | 60% |
| Role-Level Fit | 40% |

### Thresholds

| Score | Recommendation |
|-------|----------------|
| >= 70% | Apply |
| 50-69% | Consider |
| < 50% | Skip |

### Red Flags (Auto-Skip)

- Visa sponsorship required AND role says "No sponsorship"
- Location mismatch AND not remote AND not willing to relocate
- Salary > 30% above role range
- Missing 3+ required skills

---

## User-Specifiable Filters

| Filter | Default | Notes |
|--------|---------|-------|
| roles | From profile | Comma-separated if multiple |
| quantity | User-specified | Total jobs desired |
| timeline | 24hrs | e.g., "24hrs", "7days" |
| location | Profile default | e.g., "Boston", "Remote" |
| visa_status | Profile default | e.g., "STEM OPT", "H1B" |
| visa_required | Profile default | Boolean |
| work_mode | Flexible | "remote", "hybrid", "onsite" |
| score_threshold | 50% | Configurable |
| source_split | 50/50 | User can specify |

---

## Output Files

```
{repo_root}/jobs/
├── {YYYY-MM-DD}/
│   └── {YYYY-MM-DD_HH-MM-SS}/
│       ├── jobs.md                  # All jobs (Apply/Consider segregated by role)
│       └── index.md                 # Summary index
└── status/
    └── {YYYY-MM-DD}/
        └── {YYYY-MM-DD_HH-MM-SS}.md  # Status log
```

### jobs.md Structure (Proper Segregation)

```markdown
# All Jobs

## AI/ML Engineer

### ✅ Apply (Score >= 70%)
- **Job Title**
  - Company: ...
  - Location: ...
  - Work Type: ...
  - Source: Dice/Indeed
  - Salary: ...
  - Score: 75% | Apply
  - Apply: url
  - ID: ...

### 🤔 Consider (Score 50-69%)
- **Job Title**
  - ...

## Data Scientist

### ✅ Apply (Score >= 70%)
- ...

### 🤔 Consider (Score 50-69%)
- ...
```

### XLSX Columns

| Column | Description |
|--------|-------------|
| id | Unique job ID |
| externalJobId | Source-specific job ID |
| title | Job title |
| jobDescription | Job description (truncated to 500 chars) |
| salaryMin | Minimum salary |
| salaryMax | Maximum salary |
| salaryCurrency | Currency code (USD) |
| salaryType | Salary type (yearly/hourly) |
| jobTypes | Job type (Full-time/Contract) |
| workType | Work mode (remote/hybrid/onsite) |
| experienceLevel | Experience level |
| visaSponsorship | Visa sponsorship status |
| city | City |
| state | State |
| country | Country |
| remote | Remote flag |
| postedDate | Posted date |
| applyUrl | Application URL |
| easyApply | Easy Apply flag |
| companyName | Company name |
| companyIndustry | Company industry |
| companyWebsite | Company website |
| companyRating | Company rating |
| jobSource | Job source (Dice/Indeed) |
| score | Match score (0-100) |
| recommendation | Apply/Consider/Skip |
| searchTerm | Search term used |
| source | Source identifier |
| username | Candidate username |
| role | Role applied for |
| profilePath | Profile file path |
| resumePath | Resume file path |

### Status Log

```markdown
# Job Scraping Status

**Generated**: {timestamp}
**User Request**: "{request}"
**Roles**: {roles}
**Filters**: {filters}

## Results Summary

| Source | Scraped | After Filter | Notes |
|--------|---------|---------------|-------|
| Dice | X | Y | |
| Indeed | X | Y | |
| **Total** | **X** | **Y** | Target: {quantity} |

## Files Generated

- {repo_root}/jobs/{date}/{timestamp}.xlsx
- {repo_root}/jobs/status/{date}/{timestamp}.md
```

---

## MCP Requirements

| MCP | Required Tool | Purpose |
|-----|---------------|---------|
| Dice | `job_search` | Search Dice job board |
| Indeed | `job_search` | Search Indeed job board |

Setup guides:
- Dice: https://mcp.dice.com/mcp
- Indeed: https://mcp.indeed.com/claude/mcp

---

## Example Executions

### Simple Request
```
User: "Get 50 jobs for AI/ML Engineer"
→ Role: AI/ML Engineer, Quantity: 50
→ Source split: 25 Dice, 25 Indeed
→ Search terms: 2-4 per source (Set 2 + Set 3)
→ Score filter: > 50%
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### With Filters
```
User: "Get 50 jobs for AI/ML Engineer, remote, Boston, score > 70%"
→ Role: AI/ML Engineer, Location: Boston, Work Mode: remote
→ Score threshold: 70%
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Multiple Roles
```
User: "Get 50 jobs for AI/ML Engineer, Data Scientist"
→ Roles: [AI/ML Engineer, Data Scientist], 25 each
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

---

## Error Handling

| Scenario | Action |
|----------|--------|
| Profile not found | Ask user to setup profile first |
| MCP not connected | Guide user to connect, then retry |
| Zero jobs scraped | Return empty XLSX, log error |
| Score filter too strict | Lower threshold to 30%, notify user |
| Partial failure | Continue with successful sources, log failures |

---

## Best Practices

1. Always validate profile exists before scraping
2. Use Set 2 + Set 3 search terms for precision
3. Apply user filters at both search and scoring phases
4. Run source subagents in parallel for speed
5. Keep temp cleanup even on partial failure
6. Use configurable score threshold per request
7. Log status with timestamp for traceability

---

## Folder Structure

```
auto-job-hunt/
├── SKILL.md
├── scripts/
│   ├── __init__.py
│   ├── validate_profile.py
│   ├── validate_mcps.py
│   ├── planner.py
│   ├── scorer.py
│   ├── csv_generator.py
│   └── cleanup.py
├── sources/
│   ├── dice/capabilities.md
│   └── indeed/capabilities.md
└── prompts/
    ├── role_subagent.md
    ├── source_subagent.md
    └── search_term_subagent.md
```
