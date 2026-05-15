# Source Subagent Prompt

## Purpose

Search one source (MCP job board OR ATS API) for a single role using multiple search terms. Normalize results to the canonical job schema. Score all results. Return a scored job list.

## Input

You receive:
- `source`: Platform slug (`dice` / `indeed` / `greenhouse` / `lever` / `ashby` / `workable` / `smartrecruiters` / `bamboohr`)
- `source_type`: `"mcp"` or `"ats_api"`
- `role_name`: The target role (e.g., "Full Stack Engineer")
- `search_terms`: List of 2-4 search terms to execute
- `quantity_per_source`: Total jobs to fetch from this source
- `scoring_path`: Path to `scoring.md` for this role
- `profile_path`: Path to `profile.md` for this role
- `user_filters`: Dict with `location`, `visa_status`, `work_mode`, `score_threshold`, etc.
- `companies`: List of company slugs/boards to search (ATS only; empty list for MCP)

## Path Rules

Write outputs under `workspace_root()/temp/{source}/{role_name}/...`. Use `scripts/paths.py` to resolve `workspace_root()`.

---

## Process

### For MCP Sources (Dice, Indeed)

1. **Calculate jobs per term**:
   - `quantity_per_term = quantity_per_source // len(search_terms)`
   - Minimum 5, maximum 25 per term

2. **Call MCP `job_search` for each term** (in parallel if possible):

   **Dice:**
   ```
   job_search(
     query: "<search_term>",
     location: <user_filters.location or "remote">,
     remote: <true if work_mode == "remote">,
     posted: "24h",
     jobType: <"contract" if employment_type=="contract" else "fulltime">,
     count: <quantity_per_term>
   )
   ```

   **Indeed:**
   ```
   job_search(
     query: "<search_term>",
     location: <user_filters.location or "">,
     remote: <true if work_mode == "remote">,
     posted: "1h",
     jobType: <"contract" if employment_type=="contract" else "fulltime">,
     count: <quantity_per_term>
   )
   ```

3. **Normalize** each result to the canonical schema (MCP output already matches — just extract fields)

4. **Score** each job using `scorer.py` with `scoring_path`

5. **Aggregate**, remove duplicates (same `id` or same `applyUrl`), save to `workspace_root()/temp/{source}/{role_name}/jobs.md`

### For ATS API Sources (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR)

1. **Import the client**:
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path("skills/auto-job-hunt").resolve()))
   from ats_clients import get_client

   client = get_client("<source>")  # e.g. "greenhouse", "lever", "ashby"
   ```

2. **Search jobs per term**:
   ```python
   for term in search_terms:
       results = client.search_jobs(
           query=term,
           location=user_filters.get("location", ""),
           limit=quantity_per_term,
       )
       all_raw_jobs.extend(results)
   ```

3. **Normalize to canonical schema** (see mapping tables below)

4. **Score** each job using `scorer.py` with `scoring_path`

5. **Aggregate**, remove duplicates, save to `workspace_root()/temp/{source}/{role_name}/jobs.md`

---

## ATS Normalization Mappings

Use these field mappings to convert each ATS client's raw output to the canonical job schema. Missing fields → `null` (never omit the field, always include as `null`).

### Greenhouse

| Canonical Field | Greenhouse Source |
|-----------------|-------------------|
| `id` | `"greenhouse_{boardToken}_{job_id}"` |
| `title` | `title` |
| `company.name` | `company.name` or boardToken capitalized |
| `company.website` | Infer: `"https://{boardToken}.com"` (best effort) |
| `company.industry` | `null` (not in API) |
| `location.formatted` | `location.name` |
| `location.remote` | `true` if `location.name` contains "Remote" (case-insensitive) |
| `location.city` | Parse from `location.name` |
| `employment.jobTypes` | `["Full-time"]` (Greenhouse default) |
| `employment.workType` | `"remote"` if remote else `"onsite"` |
| `salary.min/max` | `null` (Greenhouse rarely exposes salary) |
| `apply.applyUrl` | `absolute_url` |
| `posting.postedDate` | `updated_at` |
| `recruiter` | `null` (not available) |
| `source` | `"greenhouse"` |

### Lever

| Canonical Field | Lever Source |
|-----------------|--------------|
| `id` | `"lever_{site}_{id}"` |
| `title` | `text` |
| `company.name` | site slug → capitalize first letter |
| `company.website` | Infer: `"https://{site}.com"` (best effort) |
| `company.industry` | `null` |
| `location.formatted` | `categories.location` |
| `location.remote` | `true` if `categories.location` contains "Remote" |
| `location.city` | Parse from `categories.location` |
| `employment.jobTypes` | `["Full-time"]` |
| `employment.workType` | Parse from `categories.commitment` or location |
| `salary.min/max` | `null` |
| `apply.applyUrl` | `hostedUrl` |
| `posting.postedDate` | `createdAt` (Unix ms → `datetime.fromtimestamp(createdAt/1000).isoformat()`) |
| `description` | `descriptionPlain` |
| `recruiter` | `null` |
| `source` | `"lever"` |

### Ashby

| Canonical Field | Ashby Source |
|-----------------|--------------|
| `id` | `"ashby_{orgSlug}_{id}"` |
| `title` | `title` |
| `company.name` | `organization.name` (from GraphQL) or orgSlug capitalized |
| `company.website` | `organization.websiteUrl` |
| `company.industry` | `null` |
| `location.formatted` | `locationName` |
| `location.remote` | `isRemote` (boolean, direct) |
| `location.city` | Parse from `locationName` if not remote |
| `employment.workType` | `"remote"` if `isRemote` else parse from `employmentType` |
| `employment.jobTypes` | Map `employmentType`: `"FullTime" → "Full-time"`, `"Contract" → "Contract"` |
| `salary.min/max` | `null` |
| `apply.applyUrl` | `"https://jobs.ashbyhq.com/{orgSlug}/{id}"` |
| `posting.postedDate` | `publishedDate` |
| `description` | Strip HTML from `descriptionHtml` |
| `recruiter` | `null` |
| `source` | `"ashby"` |

### Workable

| Canonical Field | Workable Source |
|-----------------|-----------------|
| `id` | `"workable_{subdomain}_{shortcode}"` |
| `title` | `title` |
| `company.name` | `company.name` |
| `company.website` | Infer: `"https://{subdomain}.com"` |
| `company.industry` | `null` |
| `location.formatted` | `location.city + ", " + location.country_code` |
| `location.remote` | `remote` (boolean, direct) |
| `location.city` | `location.city` |
| `location.country` | `location.country_code` |
| `employment.workType` | `"remote"` if `remote` else `"onsite"` |
| `employment.jobTypes` | `["Full-time"]` |
| `salary.min/max` | `null` |
| `apply.applyUrl` | `url` |
| `posting.postedDate` | `published_on` |
| `description` | `description` |
| `recruiter` | `null` |
| `source` | `"workable"` |

### SmartRecruiters

| Canonical Field | SmartRecruiters Source |
|-----------------|------------------------|
| `id` | `"smartrecruiters_{companyId}_{uuid}"` |
| `title` | `name` |
| `company.name` | `company.name` |
| `company.website` | `null` |
| `company.industry` | `industry.label` |
| `location.formatted` | `location.city + ", " + location.region + ", " + location.country` |
| `location.remote` | Check `typeOfWork` == "remotely" or location contains "Remote" |
| `location.city` | `location.city` |
| `location.country` | `location.country` |
| `employment.jobTypes` | Map `typeOfEmployment`: `"FULL_TIME" → "Full-time"`, `"CONTRACT" → "Contract"` |
| `employment.workType` | `"remote"` if `typeOfWork == "remotely"` else `"onsite"` |
| `salary.min/max` | `null` |
| `apply.applyUrl` | `ref` |
| `posting.postedDate` | `releasedDate` |
| `description` | `jobAd.sections.jobDescription.text` |
| `recruiter` | `null` |
| `source` | `"smartrecruiters"` |

### BambooHR

| Canonical Field | BambooHR Source |
|-----------------|-----------------|
| `id` | `"bamboohr_{subdomain}_{id}"` |
| `title` | Parsed from HTML embed |
| `company.name` | subdomain → capitalize (`"automattic"` → `"Automattic"`) |
| `company.website` | Infer: `"https://{subdomain}.com"` |
| `company.industry` | `null` |
| `location.formatted` | Parsed from HTML (often "Remote" or blank) |
| `location.remote` | `true` if location is empty or contains "Remote" |
| `employment.jobTypes` | `["Full-time"]` |
| `employment.workType` | `"remote"` if remote else `"onsite"` |
| `salary.min/max` | `null` |
| `apply.applyUrl` | `"https://{subdomain}.bamboohr.com/jobs/view.php?id={id}"` |
| `posting.postedDate` | `null` |
| `description` | Parsed from HTML |
| `recruiter` | `null` |
| `source` | `"bamboohr"` |

---

## Output Format

Save to: `workspace_root()/temp/{source}/{role_name}/jobs.md`

```markdown
# {source} Jobs: {role_name}

Total: {count} jobs found | {apply_count} Apply | {consider_count} Consider
Source Type: {mcp|ats_api}
Search Terms Used: {term1}, {term2}, ...

## Job List

### 1. {job_title}
- **Score**: {score}/100 — {recommendation}
- **Company**: {company_name}
- **Company Website**: {company_website or "N/A"}
- **Industry**: {company_industry or "N/A"}
- **Location**: {location.formatted} | Remote: {Yes/No}
- **Work Type**: {workType}
- **Job Types**: {jobTypes}
- **Salary**: {salary_range or "N/A"}
- **Recruiter**: {recruiter_name or "N/A"} | {recruiter_email or "N/A"}
- **Source**: {source}
- **Search Term**: {search_term}
- **Apply URL**: {apply_url}
- **ID**: {job_id}
```

---

## Error Handling

| Scenario | Action |
|----------|--------|
| MCP not connected | Log "source unavailable", return empty list |
| ATS client import fails | Log error with traceback, return empty list |
| ATS API returns 0 results | Log "0 results for {term}", continue to next term |
| ATS API rate limited (429) | Sleep 2s, retry once, then skip term |
| Normalization error on a job | Skip that job, log the raw data for debugging |
| Score below threshold | Exclude from output, do NOT include in file |

---

## Example

```
Input:
  source: "greenhouse"
  source_type: "ats_api"
  role_name: "Full Stack Engineer"
  search_terms: ["full stack engineer", "react node developer"]
  quantity_per_source: 10
  scoring_path: "Vikash_Mediboina/FullStackEngineer/scoring.md"
  profile_path: "Vikash_Mediboina/FullStackEngineer/profile.md"
  user_filters: {location: "Remote", work_mode: "remote", score_threshold: 50}
  companies: ["stripe", "figma", "notion", "vercel"]

Process:
  quantity_per_term = 10 // 2 = 5
  Term 1 "full stack engineer":
    → client.search_jobs("full stack engineer", location="Remote", limit=5)
    → Returns 5 raw jobs (Stripe, Figma, etc.)
    → Normalize using Greenhouse mapping table above
    → Score each job → keep those >= 50
  Term 2 "react node developer":
    → Same process, 5 more jobs
    → Deduplicate against Term 1 results
  Total: up to 10 unique scored jobs saved to temp/greenhouse/FullStackEngineer/jobs.md

Output job example:
  {
    "id": "greenhouse_stripe_123456",
    "title": "Senior Full Stack Engineer",
    "score": 82,
    "recommendation": "Apply",
    "company": {"name": "Stripe", "website": "https://stripe.com", "industry": null},
    "location": {"formatted": "Remote", "remote": true},
    "apply": {"applyUrl": "https://boards.greenhouse.io/stripe/jobs/123456"},
    "source": "greenhouse",
    "searchTerm": "full stack engineer"
  }
```
