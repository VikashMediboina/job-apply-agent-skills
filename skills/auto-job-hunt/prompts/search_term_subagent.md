# Search Term Subagent Prompt

## Purpose

Execute a single search term against one job source (Dice MCP, Indeed MCP, or an ATS API client)
and return scored, normalized jobs.

## Input

You receive:
- `search_term`: The search query string
- `source`: One of: `"dice"`, `"indeed"`, `"greenhouse"`, `"lever"`, `"ashby"`, `"workable"`, `"smartrecruiters"`, `"bamboohr"`
- `source_type`: `"mcp"` or `"ats_api"`
- `role_name`: The target role
- `quantity_per_term`: How many jobs to fetch for this term (typically 5-10)
- `scoring_path`: Path to scoring.md for this role
- `profile_path`: Path to profile.md for this role
- `companies`: (ATS only) List of company slugs/tokens to search across
- `user_filters`: Dict with:
  - `location`: Preferred location (e.g., "Boston", "Remote")
  - `work_mode`: `"remote"`, `"hybrid"`, `"onsite"`, or `"Flexible"`
  - `visa_status`: User's visa status
  - `visa_required`: Whether user needs sponsorship

## Path Rules

Write all scratch files beneath `workspace_root()/temp/` and sanitize filenames.

## Process

1. **Execute search** — use the appropriate method for `source_type`
2. **Normalize** — map raw API fields to canonical schema
3. **Score each job** — using scoring.md + profile.md
4. **Save scored jobs** — to `workspace_root()/temp/{source}/{role_name}/scored/{search_term_safe}.md`
5. **Return jobs** — list of scored job dicts

---

## Part A: MCP Sources (Dice and Indeed)

Use when `source_type == "mcp"`.

### Dice MCP call

```python
dice.job_search(
    query=search_term,
    location=user_filters.get("location", ""),
    remote=user_filters.get("work_mode") == "remote",
    posted="24h",       # valid: "1h", "24h", "3d", "7d"
    jobType="fulltime", # or "contract"
    count=quantity_per_term
)
```

### Indeed MCP call

```python
indeed.job_search(
    query=search_term,
    location=user_filters.get("location", ""),
    remote=user_filters.get("work_mode") == "remote",
    posted="1d",        # valid: "1h", "1d", "3d", "7d", "14d"  ← NOTE: "24h" is NOT valid for Indeed; use "1d"
    jobType="fulltime",
    count=quantity_per_term
)
```

MCP results are already close to the canonical schema. Map:
- `job.id` → `id`
- `job.title` → `title`
- `job.company` → `company.name`
- `job.location` → `location.formatted`
- `job.applyUrl` → `apply.applyUrl`
- `job.postedDate` → `posting.postedDate`

---

## Part B: ATS API Sources

Use when `source_type == "ats_api"`. Import the appropriate client and call `search_jobs()`.

```python
import sys
sys.path.insert(0, "skills/auto-job-hunt")
from ats_clients import get_client

client = get_client(source)  # source = "greenhouse", "lever", etc.
raw_jobs = client.search_jobs(
    query=search_term,
    companies=companies,       # list of slugs/tokens from the source plan
    limit=quantity_per_term,
    remote_only=(user_filters.get("work_mode") == "remote"),
)
```

**After getting raw_jobs, you MUST normalize each job to the canonical schema before scoring.**
Each ATS platform returns different field names. Use the tables below.

---

### Normalization Tables

#### Greenhouse

Raw API endpoint: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`

| Canonical field | Raw Greenhouse field | Notes |
|-----------------|---------------------|-------|
| `id` | `"greenhouse:" + str(job["id"])` | Prefix to avoid collisions |
| `title` | `job["title"]` | |
| `company.name` | `job["company_name"]` (or board token) | |
| `apply.applyUrl` | `job["absolute_url"]` | This is the apply URL |
| `apply.viewUrl` | `job["absolute_url"]` | Same as applyUrl for Greenhouse |
| `location.formatted` | `job["location"]["name"]` | |
| `location.remote` | `"remote" in job["location"]["name"].lower()` | |
| `posting.postedDate` | `job["updated_at"]` | ISO 8601 string |
| `jobDescription` | `job.get("content", "")` | HTML, strip tags |
| `jobSource.platform` | `"greenhouse"` | |
| `jobSource.sourceType` | `"ats"` | |

**Performance note**: Greenhouse probes up to 39 boards sequentially. Expect 10–30s per run.

#### Lever

Raw API endpoint: `https://api.lever.co/v0/postings/{site}?mode=json&skip=0&limit=250`

| Canonical field | Raw Lever field | Notes |
|-----------------|----------------|-------|
| `id` | `"lever:" + job["id"]` | Prefix to avoid collisions |
| `title` | `job["text"]` | NOT `job["title"]` |
| `company.name` | site slug (e.g., `"netflix"`) | From the board slug |
| `apply.applyUrl` | `job["hostedUrl"]` | |
| `apply.viewUrl` | `job["hostedUrl"]` | |
| `location.formatted` | `job["categories"].get("location", "")` | |
| `location.remote` | `"remote" in job["categories"].get("location", "").lower()` | |
| `posting.postedDate` | `datetime.fromtimestamp(job["createdAt"] / 1000).isoformat()` | `createdAt` is Unix **milliseconds** — divide by 1000 |
| `jobDescription` | `job.get("description", "")` | HTML |
| `employment.jobTypes` | `[job["categories"].get("commitment", "")]` | |
| `jobSource.platform` | `"lever"` | |
| `jobSource.sourceType` | `"ats"` | |

#### Ashby

Raw API endpoint: `POST https://api.ashbyhq.com/posting-api/job-board/{orgNameSlug}` with GraphQL

| Canonical field | Raw Ashby field | Notes |
|-----------------|----------------|-------|
| `id` | `"ashby:" + job["id"]` | Prefix to avoid collisions |
| `title` | `job["title"]` | |
| `company.name` | `job["company"]["name"]` or org slug | |
| `apply.applyUrl` | `job["jobUrl"]` | |
| `apply.viewUrl` | `job["jobUrl"]` | |
| `location.formatted` | `job["location"]` (string) | |
| `location.remote` | `job["isRemote"]` | Boolean — use directly |
| `posting.postedDate` | `job["publishedDate"]` | ISO 8601 |
| `jobDescription` | `job.get("descriptionHtml", "")` | HTML |
| `employment.jobTypes` | `[job.get("employmentType", "")]` | |
| `salary.min` | `job.get("compensation", {}).get("minValue")` | |
| `salary.max` | `job.get("compensation", {}).get("maxValue")` | |
| `jobSource.platform` | `"ashby"` | |
| `jobSource.sourceType` | `"ats"` | |

**Ashby is the best source for AI/ML startups** (OpenAI, Anthropic, Mistral, Cohere, etc.).

#### Workable

Raw API endpoint: `https://www.workable.com/api/jobs?query={query}&details=true&limit=50`

| Canonical field | Raw Workable field | Notes |
|-----------------|-------------------|-------|
| `id` | `"workable:" + job["shortcode"]` | Use `shortcode` not `id` |
| `title` | `job["title"]` | |
| `company.name` | `job["company"]["name"]` | |
| `apply.applyUrl` | `job["url"]` | |
| `apply.viewUrl` | `job["url"]` | |
| `location.formatted` | `job["location"]["city"] + ", " + job["location"]["country"]` | |
| `location.remote` | `job.get("remote", False)` | Boolean |
| `posting.postedDate` | `job["created_at"]` | ISO 8601 |
| `jobDescription` | `job.get("description", "")` | |
| `employment.jobTypes` | `[job.get("type", "")]` | |
| `jobSource.platform` | `"workable"` | |
| `jobSource.sourceType` | `"ats"` | |

**Note**: Workable's public board covers international companies (Europe, LATAM, APAC). Good for remote roles.

#### SmartRecruiters

Raw API endpoint: `https://api.smartrecruiters.com/v1/companies/{companyId}/postings?q={query}&limit=100`

| Canonical field | Raw SmartRecruiters field | Notes |
|-----------------|--------------------------|-------|
| `id` | `"smartrecruiters:" + job["id"]` | |
| `title` | `job["name"]` | NOT `job["title"]` |
| `company.name` | `job["company"]["name"]` | |
| `apply.applyUrl` | `"https://jobs.smartrecruiters.com/" + job["company"]["identifier"] + "/" + job["id"]` | Construct URL |
| `apply.viewUrl` | same as `applyUrl` | |
| `location.formatted` | `job["location"]["city"] + ", " + job["location"]["country"]` | |
| `location.remote` | `job["typeOfWork"]["label"] == "remotely"` | Compare label string |
| `posting.postedDate` | `job["releasedDate"]` | ISO 8601 |
| `jobDescription` | `job.get("jobDescription", {}).get("text", "")` | |
| `employment.jobTypes` | `[job.get("typeOfEmployment", {}).get("label", "")]` | |
| `jobSource.platform` | `"smartrecruiters"` | |
| `jobSource.sourceType` | `"ats"` | |

**Note**: SmartRecruiters skews toward enterprise/retail (IKEA, Walmart, McDonald's). Use Greenhouse/Lever/Ashby first for pure tech roles.

#### BambooHR

Raw API endpoint: `https://{subdomain}.bamboohr.com/careers/list` (HTML scrape, not JSON API)

| Canonical field | Raw BambooHR field | Notes |
|-----------------|-------------------|-------|
| `id` | `"bamboohr:" + job["id"]` | Parsed from HTML |
| `title` | `job["title"]` | Parsed from `<h2>` or `<h3>` |
| `company.name` | subdomain (e.g., `"stripe"`) | From the board URL |
| `apply.applyUrl` | `"https://{subdomain}.bamboohr.com/careers/" + job["id"]` | Construct URL |
| `apply.viewUrl` | same as `applyUrl` | |
| `location.formatted` | `job["location"]` | Parsed from HTML span |
| `location.remote` | `"remote" in job.get("location", "").lower()` | |
| `posting.postedDate` | `null` | BambooHR does NOT expose post dates |
| `jobDescription` | `job.get("description", "")` | HTML, may be partial |
| `jobSource.platform` | `"bamboohr"` | |
| `jobSource.sourceType` | `"ats"` | |

**Warning**: BambooHR returns 0 results for generic tech queries on its global search. It only works when you probe **specific known company subdomains**. Use only when you have a curated `companies` list. Lower priority source — use Greenhouse/Lever/Ashby first.

---

## Scoring Logic

After normalizing, score using the `scorer.py` module:

```python
from skills.auto_job_hunt.scripts import scorer

result = scorer.score_job(
    job=normalized_job,      # Must be in canonical schema
    scoring_path=scoring_path,
    profile_path=profile_path,
    user_filters=user_filters
)
# Returns: ScoreResult(score, recommendation, red_flags, breakdown)
```

Set on the job dict:
```python
normalized_job["score"] = result.score
normalized_job["recommendation"] = result.recommendation  # "Apply", "Consider", or "Skip"
normalized_job["source"] = source  # e.g., "greenhouse"
normalized_job["searchTerm"] = search_term
```

---

## Output

Save to: `workspace_root()/temp/{source}/{role_name}/scored/{sanitized_term}.md`

### Canonical Job Schema (write ALL fields, leave empty rather than omitting)

```json
{
  "id": "",
  "externalJobId": "",
  "title": "",
  "jobDescription": "",
  "jobDescriptionHTML": "",
  "salary": {
    "min": null,
    "max": null,
    "currencyCode": "",
    "type": "yearly | hourly | monthly | contract",
    "isEstimated": false
  },
  "employment": {
    "jobTypes": [],
    "workType": "onsite | remote | hybrid",
    "experienceLevel": "",
    "visaSponsorship": false,
    "contractDuration": "",
    "shift": ""
  },
  "location": {
    "formatted": "",
    "city": "",
    "state": "",
    "country": "",
    "postalCode": "",
    "latitude": null,
    "longitude": null,
    "streetAddress": "",
    "remote": false
  },
  "posting": {
    "postedDate": null,
    "expirationDate": null,
    "expired": false,
    "isRepost": false,
    "newJob": false,
    "urgentlyHiring": false,
    "highVolumeHiring": false
  },
  "apply": {
    "applyUrl": "",
    "viewUrl": "",
    "easyApply": false,
    "applicationMethod": "external | internal | email"
  },
  "company": {
    "name": "",
    "industry": "",
    "sector": "",
    "website": "",
    "description": "",
    "logoUrl": "",
    "headquarters": "",
    "employeeRange": "",
    "revenue": "",
    "rating": null,
    "reviewCount": null
  },
  "clientCompany": { "name": "", "industry": "", "website": "", "location": "", "description": "", "employeeRange": "", "revenue": "", "logoUrl": "" },
  "vendorCompany": { "name": "", "industry": "", "website": "", "location": "", "description": "", "employeeRange": "", "revenue": "", "logoUrl": "" },
  "recruiter": { "name": "", "email": "", "phone": "", "linkedin": "", "title": "", "company": "" },
  "benefits": [{"key": "", "label": ""}],
  "skills": [],
  "technologies": [],
  "attributes": [],
  "occupations": [],
  "language": "",
  "jobSource": {
    "platform": "",
    "sourceName": "",
    "sourceType": "job_board | ats | company_site | agency",
    "sourceUrl": ""
  },
  "tracking": { "trackingKey": "", "scrapedAt": null, "updatedAt": null },
  "metadata": {},
  "score": 0,
  "recommendation": "",
  "searchTerm": "",
  "source": ""
}
```

### Markdown save format

```markdown
# Jobs from: {search_term}
Source: {source}
Role: {role_name}
resume_path:{resume_path}

## Scored Jobs

### 1. {job_title}
- **Company**: {company}
- **Location**: {city}, {state} ({work_type})
- **Salary**: {salary_min} - {salary_max} {currency}
- **Score**: {score}/100 - {recommendation}
- **Breakdown**: {user_fit: X%, role_fit: Y%}
- **Red Flags**: {list or "None"}
- **Apply URL**: {url}

### 2. ...
```

---

## Error Handling

| Scenario | Action |
|----------|--------|
| MCP not connected (Dice/Indeed) | Skip this source, log "MCP unavailable", return empty list |
| ATS API rate-limited (429) | Wait 2s, retry once; if still 429 skip and log |
| ATS API returns empty list | Log "No results from {source} for '{search_term}'", return empty list |
| Normalization KeyError | Log the missing field, fill with empty string/null, continue |
| Score < 0 or > 100 | Clamp to [0, 100] before saving |

---

## Examples

### MCP Example (Dice)

```
Input:
  search_term: "RAG LangChain"
  source: "dice"
  source_type: "mcp"
  role_name: "AI/ML Engineer"
  quantity_per_term: 10
  user_filters: {location: "Boston", work_mode: "remote"}

Process:
  1. Call dice.job_search(query="RAG LangChain", remote=True, posted="24h", count=10)
  2. Get 10 raw jobs (already near-canonical)
  3. Score each with AIMLEngineer/scoring.md
  4. Save to temp/dice/AIMLEngineer/scored/rag_langchain.md

Output sample:
  [{"id": "dice_123", "title": "Senior RAG Engineer", "company": {"name": "AI Startup"},
    "score": 82, "recommendation": "Apply", "source": "dice", "searchTerm": "RAG LangChain"}]
```

### ATS Example (Greenhouse)

```
Input:
  search_term: "machine learning"
  source: "greenhouse"
  source_type: "ats_api"
  role_name: "AI/ML Engineer"
  quantity_per_term: 10
  companies: ["openai", "stripe", "airbnb", "lyft"]
  user_filters: {work_mode: "remote"}

Process:
  1. client = get_client("greenhouse")
  2. raw_jobs = client.search_jobs(query="machine learning", companies=["openai","stripe","airbnb","lyft"], limit=10)
  3. For each raw job, normalize:
     - id = "greenhouse:" + str(raw["id"])
     - title = raw["title"]
     - company.name = raw["company_name"]
     - apply.applyUrl = raw["absolute_url"]
     - location.formatted = raw["location"]["name"]
     - location.remote = "remote" in raw["location"]["name"].lower()
     - posting.postedDate = raw["updated_at"]
  4. Score each with AIMLEngineer/scoring.md
  5. Save to temp/greenhouse/AIMLEngineer/scored/machine_learning.md

Output sample:
  [{"id": "greenhouse:12345", "title": "ML Engineer", "company": {"name": "OpenAI"},
    "apply": {"applyUrl": "https://boards.greenhouse.io/openai/jobs/12345"},
    "score": 91, "recommendation": "Apply", "source": "greenhouse", "searchTerm": "machine learning"}]
```

### ATS Example (Lever — note Unix ms timestamp)

```
Input:
  source: "lever"
  companies: ["netflix", "dropbox"]
  raw job: {"id": "abc123", "text": "Senior ML Engineer", "createdAt": 1712534400000,
             "hostedUrl": "https://jobs.lever.co/netflix/abc123",
             "categories": {"location": "Remote", "commitment": "Full-time"}}

Normalization:
  id = "lever:abc123"
  title = "Senior ML Engineer"        ← from "text", not "title"
  company.name = "netflix"            ← from board slug
  apply.applyUrl = "https://jobs.lever.co/netflix/abc123"
  location.formatted = "Remote"
  location.remote = True              ← "remote" in "Remote".lower()
  posting.postedDate = datetime.fromtimestamp(1712534400000 / 1000).isoformat()
                     = "2024-04-08T00:00:00"   ← divide by 1000!
```
