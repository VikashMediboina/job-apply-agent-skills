# Lever ATS Capabilities

## Overview

Lever is a popular ATS for growth-stage startups and mid-size tech companies. This client reads job postings via the public Lever postings API — no authentication required for reading.

## API Details

- **Base URL**: `https://api.lever.co/v0/postings/{site}`
- **Auth**: None (public read-only)
- **Rate Limit**: ~60 req/min
- **Best For**: Fulltime roles, growth-stage startups, Series A-C companies

## Client Location

```
skills/auto-job-hunt/ats_clients/lever.py
```

## Key Methods

### `search_jobs(query, location=None, sites=None, limit=25)`

Search across multiple Lever sites by keyword. Internally filters by text match.

```python
from ats_clients import get_client

client = get_client("lever")
jobs = client.search_jobs(
    query="react typescript engineer",
    location="remote",
    limit=20
)
```

### `get_jobs(site, query=None, location=None, limit=25)`

Fetch all postings from one Lever site.

```python
jobs = client.get_jobs(site="plaid", query="backend", limit=10)
```

## Return Schema (per job)

```json
{
  "id": "lever_plaid_abc-123-def",
  "title": "Software Engineer, Backend",
  "company": {
    "name": "Plaid",
    "website": "https://plaid.com",
    "industry": "Fintech"
  },
  "location": {
    "city": "San Francisco",
    "state": "CA",
    "country": "US",
    "remote": false,
    "formatted": "San Francisco, CA"
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
    "postedDate": "2026-04-05T12:00:00Z"
  },
  "apply": {
    "applyUrl": "https://jobs.lever.co/plaid/abc-123-def",
    "easyApply": false
  },
  "description": "We are looking for...",
  "source": "lever",
  "site": "plaid"
}
```

## Known Sites (30+)

```
plaid, stripe, airbnb, lyft, pinterest, dropbox, square, zendesk, twilio, sendgrid,
cloudflare, figma, notion, linear, loom, airtable, brex, ramp, coinbase, robinhood,
vercel, netlify, supabase, retool, segment, mixpanel, amplitude, datadog, pagerduty,
confluent
```

Auto-expanded via `company_discovery.py` as new Lever URLs (`jobs.lever.co/{site}`) are found in MCP results.

## Normalization to Canonical Schema

| Canonical Field | Lever Source |
|-----------------|--------------|
| `id` | `"lever_{site}_{posting_id}"` |
| `title` | `text` |
| `company.name` | site slug capitalized |
| `company.website` | Inferred from site slug |
| `location.formatted` | `categories.location` |
| `location.remote` | Check if location contains "Remote" |
| `employment.jobTypes` | `["Full-time"]` (Lever default) |
| `apply.applyUrl` | `hostedUrl` |
| `posting.postedDate` | `createdAt` (Unix ms → ISO) |
| `description` | `descriptionPlain` or `description` |
| `source` | `"lever"` |

## Notes

- Lever postings don't expose salary unless the company explicitly adds it
- Job description is available as HTML (`description`) and plain text (`descriptionPlain`)
- Department/team available via `categories.department`
- No recruiter contact info available via API

## Setup

No setup required. Purely public API.
