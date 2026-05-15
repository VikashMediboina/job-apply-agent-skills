# SmartRecruiters ATS Capabilities

## Overview

SmartRecruiters is an enterprise-grade ATS used by large retail, consumer, and industrial companies. This client reads job postings via the public SmartRecruiters REST API — no authentication required for reading.

## API Details

- **Base URL**: `https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings`
- **Auth**: None (public read-only)
- **Rate Limit**: ~60 req/min
- **Best For**: Enterprise fulltime roles, retail, manufacturing, consumer goods

## Client Location

```
skills/auto-job-hunt/ats_clients/smartrecruiters.py
```

## Key Methods

### `search_jobs(query, location=None, companies=None, limit=25)`

Search across multiple SmartRecruiters company boards by keyword.

```python
from ats_clients import get_client

client = get_client("smartrecruiters")
jobs = client.search_jobs(
    query="software engineer java",
    location="remote",
    limit=20
)
```

### `search_all_jobs(query, location=None, limit=25)`

Search the SmartRecruiters global aggregated feed (searches across companies specified in `KNOWN_COMPANY_IDENTIFIERS`).

```python
jobs = client.search_all_jobs(query="data engineer python", limit=30)
```

### `get_jobs(company_id, query=None, location=None, limit=25)`

Fetch jobs from one specific company.

```python
jobs = client.get_jobs(company_id="WalmartStores", query="tech lead", limit=10)
```

## Return Schema (per job)

```json
{
  "id": "smartrecruiters_WalmartStores_abc123",
  "title": "Senior Software Engineer",
  "company": {
    "name": "Walmart",
    "website": "https://walmart.com",
    "industry": "Retail"
  },
  "location": {
    "city": "Bentonville",
    "state": "AR",
    "country": "US",
    "remote": false,
    "formatted": "Bentonville, AR, US"
  },
  "employment": {
    "jobTypes": ["Full-time"],
    "workType": "onsite"
  },
  "salary": {
    "min": null,
    "max": null,
    "currency": "USD"
  },
  "posting": {
    "postedDate": "2026-04-03T00:00:00Z"
  },
  "apply": {
    "applyUrl": "https://jobs.smartrecruiters.com/WalmartStores/abc123",
    "easyApply": false
  },
  "description": "We are looking for...",
  "source": "smartrecruiters",
  "companyIdentifier": "WalmartStores"
}
```

## Known Company Identifiers (29+)

```
IKEA, VolkswagenGroupofAmericaInc, McDonaldsCorporation, Aldi, BestBuy, CVSHealth,
WalmartStores, Costco, Target, HomeDepot, Lowes, Walgreens, Samsung, LG, Philips,
Siemens, Bosch, ABB, SchneiderElectric, Honeywell, Nestle, UnileverNorthAmerica,
PepsiCo, CocaCola, Heineken, Carrefour, Auchan, MediaMarktSaturn, DeutscheTelekom, Orange
```

**Note**: These are mostly enterprise/retail companies. For pure tech roles, Greenhouse/Lever/Ashby yield better results. SmartRecruiters is best when you want enterprise-scale company jobs.

Auto-expanded via `company_discovery.py` as new SmartRecruiters URLs are found in MCP results.

## Normalization to Canonical Schema

| Canonical Field | SmartRecruiters Source |
|-----------------|------------------------|
| `id` | `"smartrecruiters_{companyId}_{uuid}"` |
| `title` | `name` |
| `company.name` | `company.name` |
| `company.website` | Inferred from company identifier |
| `location.formatted` | `location.city + ", " + location.region + ", " + location.country` |
| `location.remote` | Check `typeOfWork` or `location` for "remote" |
| `employment.jobTypes` | `typeOfEmployment` (FULL_TIME → "Full-time") |
| `apply.applyUrl` | `ref` URL |
| `posting.postedDate` | `releasedDate` |
| `description` | `jobAd.sections.jobDescription.text` |
| `source` | `"smartrecruiters"` |

## Notes

- Best for enterprise and retail tech roles; less useful for pure tech startups
- International coverage: EU and global enterprise companies
- `typeOfWork` field captures remote/office preference
- No recruiter contact info via API

## Setup

No setup required. Purely public API.
