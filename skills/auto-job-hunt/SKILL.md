---
name: auto-job-hunt
description: Automated job searching from Dice/Indeed MCPs + 6 ATS API clients (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR) with priority-based source allocation, auto-expanding company discovery, role-specific scoring, and strict output formatting.
---

# Auto Job Hunt

## Overview

This skill automates job searching across **8 sources**: Dice and Indeed via MCP integrations, plus 6 ATS platform APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR) via direct API clients. Source allocation is priority-based — contract roles favor Dice, fulltime roles favor ATS APIs, and the system auto-discovers new companies on each run.

## When to Use

- User wants to find jobs matching their profile (requires prior profile setup via `resume-profile-generator`)
- User specifies a role and quantity (e.g., "Get 50 jobs for AI/ML Engineer")
- User wants configurable filters: location, visa status, work mode, score threshold
- User wants jobs from multiple sources (Dice + Indeed + ATS APIs) with parallel execution
- User specifies a priority: contract, fulltime, diverse, or premium

## When NOT to Use

- User has no profile setup (run `resume-profile-generator` first)
- User wants manual job search without scoring

---

## Workflow

### Phase 1: Validation

1. **Load ask-questions-if-underspecified skill** for clarifying user intent
2. **Validate profile bundle exists**: `{repo_root}/{username}/{role}/generation.md`

If validation fails:
- Profile not found → Ask user to run `resume-profile-generator` first

**MCP validation is disabled.** Dice and Indeed are attempted at runtime; if unavailable they are silently skipped. No pre-flight MCP check is performed.

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
| `source_split` | string | "50/50" (legacy) |
| `priority` | string | "diverse" |
| `employment_type` | string | null |

**Priority values:**

| Priority | Behavior |
|----------|----------|
| `contract` | Dice MCP primary (60%), Indeed secondary (25%), ATS minimal |
| `fulltime` | ATS APIs primary (70%), Dice/Indeed for volume (30%) |
| `diverse` | Balanced across all 8 sources |
| `premium` | Top-tier ATS only (Greenhouse 30%, Lever 25%, Ashby 20%) |

### Phase 3: Planning

1. **Role split**: If multiple roles → split quantity evenly (or ask user)
2. **Source allocation**: `SourceAllocator` distributes quantity across MCP + ATS sources based on priority
3. **Search terms selection**: Read from `{role}/searchterms.md`, select 2-4 per source (prioritize Set 2 + Set 3)
4. **Company discovery**: Load cached discovered companies, merge with hardcoded lists

### Phase 4: Execution

Hierarchy: **Role Subagent** → **Source Subagents** (Dice + Indeed + ATS platforms) → **Search Term Subagents** (2-4 each)

**MCP sources (Dice, Indeed):**
- Each search term subagent uses MCP `job_search` tool
- Applies scoring criteria from `{role}/scoring.md`

**ATS API sources (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR):**
- Source subagent calls `ats_clients.get_client(platform).search_jobs()`
- Searches across all known + discovered companies for that platform
- Applies same scoring criteria

After each MCP search, run `company_discovery.discover_from_job_results()` to auto-expand ATS company lists from job URLs found in Dice/Indeed results.

### Phase 5: Aggregation & Filtering

1. Each source subagent aggregates scored jobs from all its search terms
2. Role subagent collects results from ALL sources (Dice + Indeed + all 6 ATS APIs)
3. Deduplicate across sources (same job URL or same company+title+location)
4. Apply user filters + score threshold
5. If total < requested → note shortfall, suggest loosening filters or adding sources

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

**Purpose**: Orchestrate job search for a single role across all allocated sources (MCP + ATS APIs)

**Inputs**:
- role name
- quantity
- user filters (location, visa, work_mode, score_threshold)
- priority ("contract" / "fulltime" / "diverse" / "premium")
- source_plans (list from SourceAllocator — each has source, source_type, quantity, search_terms, companies)

**Outputs**:
- Aggregated scored jobs from all sources (MCP + ATS)
- Deduplicated, filtered by score threshold

### Source Subagent

**Purpose**: Search one source (MCP or ATS API)

**Inputs**:
- source name (dice/indeed/greenhouse/lever/ashby/workable/smartrecruiters/bamboohr)
- source type ("mcp" or "ats_api")
- role name
- search terms (2-4)
- quantity per term
- scoring criteria
- user filters
- companies list (ATS only)

**Outputs**:
- Aggregated scored jobs from all search terms
- Saved to `{workspace_root}/temp/{source}/{role}/jobs.md`

### Search Term Subagent

**Purpose**: Execute search for one search term on one source (MCP or ATS API)

**Inputs**:
- search term string
- source (dice / indeed / greenhouse / lever / ashby / workable / smartrecruiters / bamboohr)
- source_type ("mcp" or "ats_api")
- role name
- quantity to fetch
- scoring criteria path
- profile path
- user filters
- companies list (ATS sources only)

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
| source_split | 50/50 | Legacy: forces dice/indeed only |
| priority | diverse | "contract", "fulltime", "diverse", "premium" |
| employment_type | null | "contract", "fulltime", "c2h", "w2", "c2c" |

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

### jobs.md Structure (Strict Format)

Every job card has the SAME fields in the SAME order. Missing data = "N/A", never omitted.

```markdown
# All Jobs

## AI/ML Engineer

### Apply (Score >= 70%)

**Senior ML Engineer**
Score: 85% | Apply

- Company: TechCorp
- Company Website: https://techcorp.com
- Industry: AI/ML
- Company Size: 100-500
- Company Rating: 4.2
- Location: Boston, MA, US
- Remote: True
- Work Type: remote
- Job Types: Full-time
- Salary: $150,000 - $200,000 USD yearly
- Recruiter: Jane Smith
- Recruiter Email: jane@recruiter.com
- Recruiter Phone: 555-0100
- Recruiter LinkedIn: https://linkedin.com/in/janesmith
- Recruiter Company: TechStaffing
- Source: dice
- Source Type: job_board
- Apply: https://example.com/apply
- Easy Apply: false
- ID: abc123
- External ID: EXT001

### Consider (Score 50-69%)

**ML Engineer**
Score: 62% | Consider

- Company: DataCorp
- Company Website: N/A
- Industry: Analytics
...
```

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
| Dice | X | Y | MCP |
| Indeed | X | Y | MCP |
| Greenhouse | X | Y | ATS API |
| Lever | X | Y | ATS API |
| Ashby | X | Y | ATS API |
| Workable | X | Y | ATS API |
| SmartRecruiters | X | Y | ATS API |
| BambooHR | X | Y | ATS API |
| **Total** | **X** | **Y** | Target: {quantity} |

## Files Generated

- {repo_root}/jobs/{date}/{timestamp}/jobs.md
- {repo_root}/jobs/status/{date}/{timestamp}.md
```

---

## Sources

### MCP Sources (require MCP connection)

| MCP | Required Tool | Purpose | Best For |
|-----|---------------|---------|----------|
| Dice | `job_search` | Search Dice job board | Contract, C2H, W2 |
| Indeed | `job_search` | Search Indeed job board | Volume, diverse |

Setup guides:
- Dice: https://mcp.dice.com/mcp
- Indeed: https://mcp.indeed.com/claude/mcp

### ATS API Sources (no auth required)

| Platform | API / Method | Known Companies | Best For |
|----------|--------------|-----------------|----------|
| Greenhouse | REST `boards-api.greenhouse.io` | 39+ | Fulltime, startup, tech |
| Lever | REST `api.lever.co/v0/postings` | 30+ | Fulltime, startup, growth |
| LinkedIn | HTML scraper `linkedin.com/jobs/search` | N/A (aggregator) | Fulltime, contract, executive |
| Google Jobs | JSON-LD / SerpAPI | N/A (aggregator) | All types, widest coverage |
| Ashby | GraphQL `jobs.ashbyhq.com` | 29+ | Fulltime, modern startups |
| ZipRecruiter | JSON embed API | N/A (aggregator) | Volume, SMB, diverse |
| Workable | REST `jobs.workable.com/api/v1` | 30+ | Fulltime, SMB, international |
| Glassdoor | Public JSON search | N/A (aggregator) | Fulltime, enterprise |
| SmartRecruiters | REST `api.smartrecruiters.com` | 29+ | Enterprise, retail |
| SimplyHired | Public JSON API | N/A (aggregator) | Volume, SMB, diverse |
| Monster | Public JSON search API | N/A (aggregator) | Fulltime, enterprise |
| CareerJet | Free public JSON API | N/A (aggregator) | International, diverse |
| BambooHR | HTML embed `{sub}.bamboohr.com` | 27+ | SMB, non-tech |

ATS clients live at `ats_clients/` inside this skill. No external auth needed for reading.

### Auto-Expanding Company Discovery

When Dice/Indeed results contain apply URLs pointing to ATS platforms (e.g., `boards.greenhouse.io/stripe`), the system automatically:
1. Detects the platform from the URL
2. Extracts the company slug
3. Adds it to the discovery cache (`ats_clients/discovered_companies.json`)
4. Future runs search those companies too

This means the company lists grow with every run — starting at ~190 companies total and expanding automatically.

---

## Example Executions

### Simple Request (diverse priority — default)
```
User: "Get 50 jobs for AI/ML Engineer"
→ Role: AI/ML Engineer, Quantity: 50, Priority: diverse
→ Sources: Dice(8), Indeed(7), LinkedIn(6), Greenhouse(5), Google Jobs(5), Lever(4), Ashby(4), ZipRecruiter(3), Workable(3), Glassdoor(2), SmartRecruiters(1), SimplyHired(1), Monster(1)
→ Search terms: 2-4 per source (Set 2 + Set 3)
→ Score filter: > 50%
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Contract Priority
```
User: "Get 50 contract jobs for DevOps Engineer"
→ Role: DevOps Engineer, Quantity: 50, Priority: contract
→ Sources: Dice(20), Indeed(10), LinkedIn(8), Google Jobs(5), ZipRecruiter(4), Greenhouse(3)
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Fulltime Priority
```
User: "Get 80 fulltime jobs for Full Stack Engineer"
→ Role: Full Stack Engineer, Quantity: 80, Priority: fulltime
→ Sources: Greenhouse(10), Lever(9), LinkedIn(9), Ashby(8), Google Jobs(8), Indeed(8), Dice(8), ZipRecruiter(6), Workable(6), Glassdoor(4), SmartRecruiters(4), SimplyHired(2), Monster(2), BambooHR(2), CareerJet(2), BambooHR(1)
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Premium (Top-Tier ATS)
```
User: "Get 30 premium jobs for ML Engineer"
→ Role: ML Engineer, Quantity: 30, Priority: premium
→ Sources: Greenhouse(9), Lever(8), Ashby(6), Dice(3), Indeed(2), Workable(2)
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### With Filters
```
User: "Get 50 jobs for AI/ML Engineer, remote, Boston, score > 70%"
→ Role: AI/ML Engineer, Location: Boston, Work Mode: remote
→ Score threshold: 70%, Priority: diverse (default)
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Multiple Roles
```
User: "Get 50 jobs for AI/ML Engineer, Data Scientist"
→ Roles: [AI/ML Engineer, Data Scientist], 25 each
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

### Legacy Mode (explicit split)
```
User: "Get 50 jobs for AI/ML Engineer 60/40 dice"
→ Legacy mode: 30 Dice, 20 Indeed (no ATS sources)
→ Output: {repo_root}/jobs/2026-04-07/2026-04-07_14-30-00/jobs.md
```

---

## Error Handling

| Scenario | Action |
|----------|--------|
| Profile not found | Ask user to setup profile first |
| MCP not connected | Silently skip that source, continue with others |
| Zero jobs scraped | Return empty jobs.md, log error, suggest loosening filters |
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
├── ats_clients/                        # ATS API clients (self-contained)
│   ├── __init__.py                     # Registry + helpers
│   ├── company_discovery.py            # Auto-expand module
│   ├── discovered_companies.json       # Persistent discovery cache
│   ├── greenhouse.py                   # Greenhouse API client
│   ├── lever.py                        # Lever API client
│   ├── ashby.py                        # Ashby GraphQL client
│   ├── workable.py                     # Workable API client
│   ├── smartrecruiters.py              # SmartRecruiters API client
│   └── bamboohr.py                     # BambooHR client
├── scripts/
│   ├── __init__.py
│   ├── validate_profile.py
│   ├── validate_mcps.py
│   ├── planner.py                      # SourceAllocator + priority-based planning
│   ├── scorer.py
│   ├── md_generator.py                 # Strict format with all fields
│   ├── csv_generator.py
│   ├── source_metrics.py               # Learning hooks + source performance
│   ├── cleanup.py
│   ├── run.py
│   ├── paths.py
│   └── validate_links.py
├── sources/
│   ├── dice/capabilities.md
│   └── indeed/capabilities.md
├── prompts/
│   ├── role_subagent.md
│   ├── source_subagent.md
│   └── search_term_subagent.md
└── instincts/
    └── instincts.json
```
