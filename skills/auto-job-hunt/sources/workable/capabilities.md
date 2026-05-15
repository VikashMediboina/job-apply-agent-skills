# Workable ATS Capabilities

## Overview

Workable is a widely-used ATS for SMBs and international companies. This client supports two modes: a **public global board** (no auth, broad search) and **company-specific SPI v3** (needs API key per company). The public global board is used by default.

## API Details

- **Public Board**: `https://jobs.workable.com/api/v1/jobs` — no auth required
- **Company SPI v3**: `https://{subdomain}.workable.com/spi/v3/jobs` — needs API key
- **Auth**: None for public board; API key per company for SPI v3
- **Rate Limit**: ~60 req/min (public board)
- **Best For**: Fulltime roles, SMBs, international companies, PLG SaaS

## Client Location

```
skills/auto-job-hunt/ats_clients/workable.py
```

## Key Methods

### `search_jobs(query, location=None, subdomains=None, limit=25)`

Search the public Workable board. Filters by keyword and optional location.

```python
from ats_clients import get_client

client = get_client("workable")
jobs = client.search_jobs(
    query="product engineer react",
    location="remote",
    limit=20
)
```

### `get_jobs(subdomain, query=None, location=None, limit=25)`

Fetch jobs from a specific company's Workable board.

```python
jobs = client.get_jobs(subdomain="typeform", query="frontend", limit=10)
```

## Return Schema (per job)

```json
{
  "id": "workable_typeform_abc123",
  "title": "Frontend Engineer",
  "company": {
    "name": "Typeform",
    "website": "https://typeform.com",
    "industry": "SaaS"
  },
  "location": {
    "city": "Barcelona",
    "state": "",
    "country": "ES",
    "remote": false,
    "formatted": "Barcelona, Spain"
  },
  "employment": {
    "jobTypes": ["Full-time"],
    "workType": "onsite"
  },
  "salary": {
    "min": null,
    "max": null,
    "currency": "EUR"
  },
  "posting": {
    "postedDate": "2026-04-04T00:00:00Z"
  },
  "apply": {
    "applyUrl": "https://apply.workable.com/typeform/j/abc123",
    "easyApply": false
  },
  "description": "We are looking for...",
  "source": "workable",
  "subdomain": "typeform"
}
```

## Known Subdomains (30+)

```
zendesk, postman, semrush, hubspot, typeform, intercom, zapier, buffer, mailchimp,
wistia, hotjar, mixpanel, segment, heap, amplitude, pendo, fullstory, looker, domo,
chartio, brex, figma, notion, loom, airtable, gusto, lattice, rippling, deel, remote
```

Auto-expanded via `company_discovery.py` as new Workable URLs (`apply.workable.com/{company}`) are found in MCP results.

## Normalization to Canonical Schema

| Canonical Field | Workable Source |
|-----------------|-----------------|
| `id` | `"workable_{subdomain}_{shortcode}"` |
| `title` | `title` |
| `company.name` | `company.name` |
| `company.website` | Inferred from subdomain |
| `location.formatted` | `location.city + ", " + location.country` |
| `location.remote` | `remote` boolean field |
| `employment.workType` | `"remote"` if `remote=true`, else `"onsite"` |
| `apply.applyUrl` | `url` |
| `posting.postedDate` | `published_on` |
| `description` | `description` (plain text) |
| `source` | `"workable"` |

## Notes

- Public board returns jobs from ALL Workable companies (not just known ones) — good for broad search
- International coverage is stronger than Dice/Indeed (EU, LATAM, APAC)
- No recruiter info exposed via API

## Setup

No setup required for public board mode. Purely public API.
