# Search Term Subagent Prompt

## Purpose

Execute a single search term against one job board (Dice or Indeed) and return scored jobs.

## Input

You receive:
- `search_term`: The search query string
- `source`: "dice" or "indeed"
- `role_name`: The target role
- `quantity_per_term`: How many jobs to fetch for this term (typically 5-10)
- `scoring_path`: Path to scoring.md for this role
- `profile_path`: Path to profile.md for this role
- `user_filters`: Dict with:
  - `location`: Preferred location (e.g., "Boston", "Remote")
  - `work_mode`: "remote", "hybrid", "onsite", or "Flexible"
  - `visa_status`: User's visa status
  - `visa_required`: Whether user needs sponsorship

## Path Rules

Write all scratch files beneath `workspace_root()/temp/` and sanitize filenames.

## Process

1. **Execute MCP search**:
   - Use the appropriate MCP tool for the source
   - Pass search_term as query
   - Apply user_filters as search parameters
   - Fetch quantity_per_term jobs

2. **Score each job**:
   - Load scoring criteria from scoring_path
   - Load profile data from profile_path
   - Apply scoring algorithm to each job
   - Calculate score (0-100)
   - Determine recommendation (Apply/Consider/Skip)

3. **Save scored jobs**:
    - Save to `workspace_root()/temp/{source}/{role_name}/scored/{search_term_safe}.md`
   - Each job should have: score, recommendation, red_flags, score_breakdown

4. **Return jobs**:
   - Return list of scored job dictionaries

## MCP Calls

### Dice job_search:
```python
dice.job_search(
    query=search_term,
    location=user_filters.get("location", ""),
    remote=user_filters.get("work_mode") == "remote",
    posted="24h",  # or timeline from request
    jobType="fulltime",
    count=quantity_per_term
)
```

### Indeed job_search:
```python
indeed.job_search(
    query=search_term,
    location=user_filters.get("location", ""),
    remote=user_filters.get("work_mode") == "remote",
    posted="24h",
    jobType="fulltime",
    count=quantity_per_term
)
```

## Scoring Logic

Use the `scorer.py` module to score jobs:

```python
from skills.auto_job_hunt.scripts import scorer

result = scorer.score_job(
    job=job_dict,
    scoring_path=scoring_path,
    profile_path=profile_path,
    user_filters=user_filters
)
# Returns: ScoreResult(score, recommendation, red_flags, breakdown)
```

## Output

Save to: `workspace_root()/temp/{source}/{role_name}/scored/{sanitized_term}.md`

### Detailed Save Format

Store every result as a full job object that preserves the canonical schema below. Keep fields that are empty rather than dropping them so later consolidation can remain lossless.

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
  "clientCompany": {
    "name": "",
    "industry": "",
    "website": "",
    "location": "",
    "description": "",
    "employeeRange": "",
    "revenue": "",
    "logoUrl": ""
  },
  "vendorCompany": {
    "name": "",
    "industry": "",
    "website": "",
    "location": "",
    "description": "",
    "employeeRange": "",
    "revenue": "",
    "logoUrl": ""
  },
  "recruiter": {
    "name": "",
    "email": "",
    "phone": "",
    "linkedin": "",
    "title": "",
    "company": ""
  },
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
  "tracking": {
    "trackingKey": "",
    "scrapedAt": null,
    "updatedAt": null
  },
  "metadata": {},
  "score": 0,
  "recommendation": "",
  "searchTerm": "",
  "source": ""
}
```

Write the full array of job objects to the term file and keep the score metadata alongside the raw job content.

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

## Example

```
Input:
  search_term: "RAG LangChain"
  source: "dice"
  role_name: "AI/ML Engineer"
  quantity_per_term: 10
  scoring_path: "Jobs-skill/Vikash_Mediboina/AIMLEngineer/scoring.md"
  profile_path: "Jobs-skill/Vikash_Mediboina/AIMLEngineer/profile.md"
  user_filters: {location: "Boston", work_mode: "remote"}

Process:
  1. Call dice.job_search with query="RAG LangChain", remote=true, count=10
  2. Get 10 jobs
  3. For each job:
     - Score using AIMLEngineer/scoring.md
     - Calculate user-level fit (60%) + role-level fit (40%)
  4. Save 10 scored jobs to `workspace_root()/temp/dice/AIMLEngineer/scored/rag_langchain.md`
  5. Return list of 10 scored jobs

Output:
  [
    {
      "id": "dice_123",
      "title": "Senior RAG Engineer",
      "company": {"name": "AI Startup"},
      "score": 82,
      "recommendation": "Apply",
      "searchTerm": "RAG LangChain",
      "source": "dice"
    },
    ...
  ]
```
