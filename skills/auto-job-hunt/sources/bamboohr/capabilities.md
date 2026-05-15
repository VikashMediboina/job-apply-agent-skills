# BambooHR ATS Capabilities

## Overview

BambooHR is an HR platform used by many SMBs, content companies, and non-tech-first organizations. This client reads job postings via the public BambooHR embed endpoint — no authentication required. **Note: BambooHR is company-internal boards; results depend heavily on which companies are actively hiring.**

## API Details

- **Endpoint**: `https://{subdomain}.bamboohr.com/jobs/embed2.php`
- **Auth**: None (public HTML embed)
- **Protocol**: HTML parsing (BeautifulSoup or regex fallback)
- **Rate Limit**: ~30 req/min (be conservative)
- **Best For**: SMB fulltime roles, content companies, non-tech-primary orgs

## Client Location

```
skills/auto-job-hunt/ats_clients/bamboohr.py
```

## Key Methods

### `search_jobs(query, location=None, subdomains=None, limit=25)`

Search across multiple BambooHR company boards by keyword.

```python
from ats_clients import get_client

client = get_client("bamboohr")
jobs = client.search_jobs(
    query="software engineer",
    location=None,   # BambooHR rarely filters by location in embed
    limit=20
)
```

### `get_jobs(subdomain, query=None, location=None, limit=25)`

Fetch jobs from one specific BambooHR company subdomain.

```python
jobs = client.get_jobs(subdomain="automattic", query="engineer", limit=10)
```

## Return Schema (per job)

```json
{
  "id": "bamboohr_automattic_42",
  "title": "Backend Engineer",
  "company": {
    "name": "Automattic",
    "website": "https://automattic.com",
    "industry": "Technology"
  },
  "location": {
    "city": "",
    "state": "",
    "country": "US",
    "remote": true,
    "formatted": "Remote"
  },
  "employment": {
    "jobTypes": ["Full-time"],
    "workType": "remote"
  },
  "salary": {
    "min": null,
    "max": null,
    "currency": "USD"
  },
  "posting": {
    "postedDate": null
  },
  "apply": {
    "applyUrl": "https://automattic.bamboohr.com/jobs/view.php?id=42",
    "easyApply": false
  },
  "description": "We are looking for...",
  "source": "bamboohr",
  "subdomain": "automattic"
}
```

## Known Subdomains (27+)

```
zendesk, hootsuite, samba, soundcloud, etsy, wikimedia, mozilla, automattic, basecamp,
fastly, cloudinary, imgix, contentful, sanity, storyblok, prismic, butter, strapi,
directus, ghost, webflow, framer, invisionapp, drift, intercom, clubhouse, vercel, netlify
```

Auto-expanded via `company_discovery.py` as new BambooHR URLs (`{subdomain}.bamboohr.com`) are found in MCP results.

## Normalization to Canonical Schema

| Canonical Field | BambooHR Source |
|-----------------|-----------------|
| `id` | `"bamboohr_{subdomain}_{job_id}"` |
| `title` | Parsed from HTML embed |
| `company.name` | subdomain capitalized (e.g., `automattic` → `Automattic`) |
| `company.website` | Inferred from subdomain |
| `location.formatted` | Parsed from HTML (often "Remote" or blank) |
| `location.remote` | Check if location contains "Remote" or location is blank |
| `apply.applyUrl` | `"https://{subdomain}.bamboohr.com/jobs/view.php?id={id}"` |
| `posting.postedDate` | Often unavailable (null) |
| `description` | Parsed from HTML |
| `source` | `"bamboohr"` |

## Notes

- **Returns 0 results** for generic tech queries against most boards — boards are small and company-internal
- Best yield when searching by company name rather than generic role titles
- **Low priority source** for tech roles; use Greenhouse/Lever/Ashby first
- HTML parsing is fragile — embed structure may change per company
- Posting dates often unavailable
- No recruiter contact info available

## When to Use BambooHR

- User specifically wants to apply to SMB companies or content/media companies
- User has a specific company list that uses BambooHR
- Broad search fallback when other ATS sources are exhausted

## Setup

No setup required. Parses public embed HTML.
