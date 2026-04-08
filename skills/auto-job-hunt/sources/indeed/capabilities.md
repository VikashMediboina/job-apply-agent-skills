# Indeed MCP Capabilities

## Overview

Indeed MCP provides job search capabilities through the Indeed job platform.

## Available Tools

### job_search

Search for jobs on Indeed.

**Parameters:**
```json
{
  "query": "string",           // Search query (job title, skills, etc.)
  "location": "string",        // Location (city, state, or "remote")
  "radius": "number",          // Radius in miles (default: 25)
  "remote": "boolean",        // Filter for remote jobs only
  "posted": "string",          // Posted within: "1h", "3d", "7d", "14d", "30d"
  "jobType": "string",         // Job type: "fulltime", "contract", "parttime", "temporary"
  "expLevel": "string",        // Experience level: "entry_level", "mid_level", "senior_level"
  "company": "string",         // Company name filter
  "salary": "number",          // Minimum salary (hourly or yearly based on locale)
  "sort": "string",           // Sort by: "date", "relevance", "salary"
  "page": "number",            // Page number (default: 0)
  "count": "number"            // Results per page (default: 25, max: 50)
}
```

**Example:**
```json
{
  "query": "AI ML Engineer Python RAG",
  "location": "Boston, MA",
  "remote": true,
  "posted": "24h",
  "jobType": "fulltime",
  "expLevel": "mid_level",
  "count": 25
}
```

**Returns:**
```json
{
  "jobs": [
    {
      "id": "indeed_abc123",
      "externalJobId": "abc123",
      "title": "Machine Learning Engineer",
      "jobDescription": "We are looking for a Machine Learning Engineer...",
      "jobDescriptionHTML": "<div>We are looking for a Machine Learning Engineer...</div>",
      "salary": {
        "min": 130000,
        "max": 170000,
        "currencyCode": "USD",
        "type": "yearly",
        "isEstimated": true
      },
      "employment": {
        "jobTypes": ["Full-time"],
        "workType": "hybrid",
        "experienceLevel": "Mid to Senior Level",
        "visaSponsorship": false
      },
      "location": {
        "formatted": "Boston, MA 02101",
        "city": "Boston",
        "state": "MA",
        "country": "US",
        "postalCode": "02101",
        "remote": false
      },
      "posting": {
        "postedDate": "2026-04-07T08:00:00Z",
        "expired": false,
        "newJob": true
      },
      "apply": {
        "applyUrl": "https://www.indeed.com/jobs/abc123",
        "easyApply": true,
        "applicationMethod": "external"
      },
      "company": {
        "name": "Innovation Labs",
        "industry": "Technology",
        "website": "https://innovationlabs.io",
        "rating": 4.2,
        "reviewCount": 125
      },
      "benefits": [
        {"key": "health_insurance", "label": "Health Insurance"},
        {"key": "401k", "label": "401(k) Matching"}
      ],
      "skills": ["Python", "TensorFlow", "PyTorch", "ML"],
      "jobSource": {
        "platform": "indeed",
        "sourceName": "Indeed",
        "sourceType": "job_board"
      }
    }
  ],
  "totalCount": 89,
  "page": 0,
  "totalPages": 4
}
```

## Additional Tools

### company_information (Optional)

Get detailed company information.

**Parameters:**
```json
{
  "company": "string"         // Company name
}
```

## Notes

- Requires Indeed account connected via MCP
- Rate limit: ~30 requests/minute (may vary)
- Best for: Broad job search across all industries
- Geographic coverage: Global (US, UK, Canada, etc.)

## Important Notes

1. **Login Required**: Indeed MCP may require authentication for full access
2. **Easy Apply**: Indeed jobs often support quick apply via Indeed
3. **Salary Data**: Indeed provides estimated salary ranges for many jobs
4. **Reviews**: Company ratings and reviews are available

## Setup

1. Visit https://mcp.indeed.com/claude/mcp
2. Sign in with Indeed account
3. Authorize the MCP integration
4. Verify with `claude mcp list`

## Comparison with Dice

| Feature | Dice | Indeed |
|---------|------|--------|
| Focus | Tech/Engineering | All industries |
| Salary Data | Yes | Yes (estimated) |
| Easy Apply | Limited | Yes |
| Company Reviews | No | Yes |
| Remote Filter | Yes | Yes |
| US Coverage | Primary | Global |
