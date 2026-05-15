# Role Subagent Prompt

## Purpose

Orchestrate job search for a single role across all allocated sources (MCP + ATS APIs).

## Input

You receive:
- `role_name`: The target role (e.g., "AI/ML Engineer")
- `quantity`: Total jobs to find for this role
- `user_filters`: Dict with location, visa_status, work_mode, score_threshold
- `priority`: Source allocation priority ("contract", "fulltime", "diverse", "premium")
- `source_plans`: List of SourcePlan objects from the allocator, each containing:
  - `source`: Platform name (dice/indeed/greenhouse/lever/ashby/workable/smartrecruiters/bamboohr)
  - `source_type`: "mcp" or "ats_api"
  - `quantity`: Jobs to fetch from this source
  - `search_terms`: List of search terms
  - `companies`: List of company slugs (ATS only)
- `profile_path`: Path to role profile.md
- `scoring_path`: Path to role scoring.md

## Path Rules

Resolve all paths via `scripts/paths.py`. Do not hardcode absolute locations.

## Process

1. **Review the allocation plan**:
   - The `source_plans` list tells you exactly which sources to search and how many jobs from each
   - MCP sources (dice, indeed) use the MCP `job_search` tool
   - ATS sources (greenhouse, lever, etc.) use `ats_clients.get_client(platform).search_jobs()`

2. **Launch source subagents in parallel**:
   - For EACH source in `source_plans`, launch a source_subagent with:
     - source name and type
     - search terms
     - quantity for that source
     - companies list (ATS only)
     - scoring + profile paths
     - user filters
   - All source subagents run in parallel regardless of type

3. **Run company discovery on MCP results**:
   - After MCP source subagents return, extract ATS company slugs from job URLs
   - Call `ats_clients.company_discovery.discover_from_job_results(mcp_jobs)`
   - This auto-expands the known company lists for future runs

4. **Aggregate results**:
   - Collect scored jobs from ALL sources: Dice + Indeed + Greenhouse + Lever + Ashby + Workable + SmartRecruiters + BambooHR
   - Deduplicate: same `id`, same `applyUrl`, OR same `company.name + title + location.formatted`
   - Apply score threshold filter (discard jobs below `user_filters.score_threshold`)
   - Sort: Apply first (score desc), then Consider (score desc)
   - Return final deduplicated, sorted list

## Output

Return a list of jobs with:
- All job fields from the source (matching the canonical schema)
- `score`: 0-100
- `recommendation`: "Apply" / "Consider" / "Skip"
- `source`: platform slug (dice/indeed/greenhouse/lever/ashby/workable/smartrecruiters/bamboohr)
- `searchTerm`: Which search term found this job
- `company`: Full company object with name, website, industry, rating
- `recruiter`: Recruiter object with name, email, linkedin (when available)

## Example

```
Input:
  role_name: "Full Stack Engineer"
  quantity: 50
  priority: "fulltime"
  user_filters: {location: "Remote", work_mode: "remote", score_threshold: 50}
  source_plans:
    - {source: "greenhouse", source_type: "ats_api", quantity: 10, companies: ["stripe", "airbnb", ...]}
    - {source: "lever", source_type: "ats_api", quantity: 8, companies: ["netflix", "figma", ...]}
    - {source: "ashby", source_type: "ats_api", quantity: 8, companies: ["ramp", "linear", ...]}
    - {source: "dice", source_type: "mcp", quantity: 8, search_terms: [...]}
    - {source: "indeed", source_type: "mcp", quantity: 8, search_terms: [...]}
    - {source: "workable", source_type: "ats_api", quantity: 4, companies: [...]}
    - {source: "smartrecruiters", source_type: "ats_api", quantity: 2, companies: [...]}
    - {source: "bamboohr", source_type: "ats_api", quantity: 2, companies: [...]}

Output:
  [
    {
      "id": "...",
      "title": "Senior Full Stack Engineer",
      "score": 82,
      "recommendation": "Apply",
      "source": "greenhouse",
      "searchTerm": "full stack engineer",
      "company": {"name": "Stripe", "website": "https://stripe.com", "industry": "Fintech"},
      "recruiter": {"name": "...", "email": "...", "linkedin": "..."}
    },
    ...
  ]
```
