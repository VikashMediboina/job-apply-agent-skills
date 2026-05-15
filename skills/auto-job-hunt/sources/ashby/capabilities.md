# Ashby ATS Capabilities

## Overview

Ashby is an emerging ATS favored by modern AI and infrastructure startups. This client reads job postings via the public Ashby GraphQL API — no authentication required for reading.

## API Details

- **Base URL**: `https://jobs.ashbyhq.com/api/non-user-graphql`
- **Auth**: None (public read-only)
- **Protocol**: GraphQL POST
- **Rate Limit**: ~30 req/min (slower than REST)
- **Best For**: Fulltime roles, AI/ML startups, developer tools companies

## Client Location

```
skills/auto-job-hunt/ats_clients/ashby.py
```

## Key Methods

### `search_jobs(query, location=None, orgs=None, limit=25)`

Search across multiple Ashby orgs by keyword.

```python
from ats_clients import get_client

client = get_client("ashby")
jobs = client.search_jobs(
    query="machine learning engineer",
    location="remote",
    limit=20
)
```

### `list_jobs(org_slug, query=None, location=None, limit=25)`

Fetch all postings from one Ashby org.

```python
jobs = client.list_jobs(org_slug="openai", query="ml engineer", limit=10)
```

## Return Schema (per job)

```json
{
  "id": "ashby_openai_abc123",
  "title": "Research Engineer",
  "company": {
    "name": "OpenAI",
    "website": "https://openai.com",
    "industry": "Artificial Intelligence"
  },
  "location": {
    "city": "San Francisco",
    "state": "CA",
    "country": "US",
    "remote": true,
    "formatted": "San Francisco, CA (Remote)"
  },
  "employment": {
    "jobTypes": ["Full-time"],
    "workType": "hybrid"
  },
  "salary": {
    "min": null,
    "max": null,
    "currency": "USD"
  },
  "posting": {
    "postedDate": "2026-04-06T00:00:00Z"
  },
  "apply": {
    "applyUrl": "https://jobs.ashbyhq.com/openai/abc123",
    "easyApply": false
  },
  "description": "We are looking for...",
  "source": "ashby",
  "orgSlug": "openai"
}
```

## Known Orgs (29+)

```
openai, anthropic, mistral, cohere, scale-ai, huggingface, replit, supabase, vercel,
railway, planetscale, neon, turso, convex, lancedb, weaviate, qdrant, chroma, pinecone,
langchain, groq, together-ai, perplexity, cursor, codeium, anyscale, modal, replicate,
weights-biases, dbt-labs
```

Auto-expanded via `company_discovery.py` as new Ashby URLs (`jobs.ashbyhq.com/{org}`) are found in MCP results.

## Normalization to Canonical Schema

| Canonical Field | Ashby Source |
|-----------------|--------------|
| `id` | `"ashby_{orgSlug}_{jobId}"` |
| `title` | `title` |
| `company.name` | `organization.name` or orgSlug capitalized |
| `company.website` | `organization.websiteUrl` |
| `location.formatted` | `locationName` or `isRemote=true → "Remote"` |
| `location.remote` | `isRemote` |
| `employment.workType` | `employmentType` mapped to remote/hybrid/onsite |
| `apply.applyUrl` | `"https://jobs.ashbyhq.com/{orgSlug}/{jobId}"` |
| `posting.postedDate` | `publishedDate` |
| `description` | `descriptionHtml` (strip HTML) |
| `source` | `"ashby"` |

## Notes

- GraphQL API is more structured than REST — fields are explicit
- `isRemote` field is reliable for remote detection
- Job description available as HTML — strip tags for plain text
- Department available via `department.name`
- No recruiter contact info available via API

## Setup

No setup required. Purely public GraphQL API.
