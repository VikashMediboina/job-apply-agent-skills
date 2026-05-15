# Greenhouse ATS Capabilities

## Overview

Greenhouse is a widely-used ATS for tech companies and startups. This client reads job postings via the public Greenhouse Job Board API — no authentication required for reading.

## API Details

- **Base URL**: `https://boards-api.greenhouse.io/v1/boards`
- **Auth**: None (public read-only)
- **Rate Limit**: ~60 req/min (be gentle; probe sequentially with small delays)
- **Best For**: Fulltime roles, tech startups, Series B+ companies

## Client Location

```
skills/auto-job-hunt/ats_clients/greenhouse.py
```

## Key Methods

### `search_jobs(query, location=None, boards=None, limit=25)`

Search across multiple boards by keyword. Internally calls `get_jobs()` per board and filters by query.

```python
from ats_clients import get_client

client = get_client("greenhouse")
jobs = client.search_jobs(
    query="full stack engineer",
    location="remote",
    limit=20
)
```

### `get_jobs(board_token, query=None, location=None, limit=25)`

Fetch jobs from one specific board token.

```python
jobs = client.get_jobs(board_token="stripe", query="backend engineer", limit=10)
```

### `search_public_boards(query, boards=None, location=None, limit=25)`

Searches across all `boards` list (defaults to `KNOWN_BOARD_TOKENS`).

## Return Schema (per job)

```json
{
  "id": "greenhouse_stripe_12345",
  "title": "Senior Backend Engineer",
  "company": {
    "name": "Stripe",
    "website": "https://stripe.com",
    "industry": "Fintech"
  },
  "location": {
    "city": "San Francisco",
    "state": "CA",
    "country": "US",
    "remote": true,
    "formatted": "San Francisco, CA"
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
    "postedDate": "2026-04-07T00:00:00Z"
  },
  "apply": {
    "applyUrl": "https://boards.greenhouse.io/stripe/jobs/12345",
    "easyApply": false
  },
  "source": "greenhouse",
  "boardToken": "stripe"
}
```

## Known Board Tokens (39+)

```
airbnb, stripe, databricks, openai, anthropic, figma, notion, linear, vercel, github,
gitlab, cloudflare, hashicorp, datadog, snowflakecomputing, confluent, elastic, twilio,
hubspot, coinbase, lyft, doordash, robinhood, plaid, brex, ramp, scale, airtable,
retool, segment, mixpanel, amplitude, asana, intercom, zendesk, okta, pagerduty,
digitalocean, mongodb
```

Auto-expanded via `company_discovery.py` as new Greenhouse URLs are found in MCP results.

## Normalization to Canonical Schema

When normalizing Greenhouse output to the canonical job schema:

| Canonical Field | Greenhouse Source |
|-----------------|-------------------|
| `id` | `"greenhouse_{boardToken}_{job_id}"` |
| `title` | `title` |
| `company.name` | `company.name` or board token capitalized |
| `company.website` | Inferred from board token (e.g., `https://stripe.com`) |
| `location.formatted` | `location.name` |
| `location.remote` | Check if location contains "Remote" |
| `apply.applyUrl` | `absolute_url` |
| `posting.postedDate` | `updated_at` |
| `source` | `"greenhouse"` |

## Notes

- **Slow**: probes 39 boards sequentially — expect 10-30s for full search
- Salary data rarely present in Greenhouse API (companies don't always expose it)
- No recruiter contact info available via API
- Company industry must be inferred or left as N/A

## Setup

No setup required. Purely public API.
