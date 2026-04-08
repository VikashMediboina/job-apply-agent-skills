# Dice MCP Capabilities

## Overview

Dice MCP provides job search capabilities through the Dice career platform.

## Available Tools

### job_search

Search for jobs on Dice.

**Parameters:**
```json
{
  "query": "string",           // Search query (job title, skills, etc.)
  "location": "string",        // Location (city, state, or "remote")
  "radius": "number",          // Radius in miles (default: 50)
  "remote": "boolean",         // Filter for remote jobs only
  "posted": "string",          // Posted within: "24h", "3d", "7d", "14d", "30d"
  "jobType": "string",         // Job type: "fulltime", "contract", "parttime", "internship"
  "expLevel": "string",        // Experience level: "entry", "mid", "senior", "executive"
  "company": "string",         // Company name filter
  "salary": "number",          // Minimum salary (yearly)
  "sort": "string",           // Sort by: "relevance", "date", "salary"
  "page": "number",            // Page number (default: 1)
  "count": "number"           // Results per page (default: 25, max: 100)
}
```

**Example:**
```json
{
  "query": "AI Engineer Python LangChain",
  "location": "Boston, MA",
  "remote": true,
  "posted": "24h",
  "jobType": "fulltime",
  "expLevel": "mid",
  "count": 25
}
```

**Returns:**
```json
{
  "jobs": [
    {
      "id": "dice_123456",
      "externalJobId": "DICE-123456",
      "title": "AI/ML Engineer",
      "jobDescription": "Looking for...",
      "jobDescriptionHTML": "<p>Looking for...</p>",
      "salary": {
        "min": 120000,
        "max": 180000,
        "currencyCode": "USD",
        "type": "yearly",
        "isEstimated": false
      },
      "employment": {
        "jobTypes": ["Full-time"],
        "workType": "remote",
        "experienceLevel": "Mid-Level",
        "visaSponsorship": false
      },
      "location": {
        "formatted": "Remote",
        "city": "",
        "state": "",
        "country": "US",
        "remote": true
      },
      "posting": {
        "postedDate": "2026-04-07T12:00:00Z",
        "expired": false
      },
      "apply": {
        "applyUrl": "https://www.dice.com/job/123456",
        "easyApply": false,
        "applicationMethod": "external"
      },
      "company": {
        "name": "TechCorp",
        "industry": "Computer Software",
        "website": "https://techcorp.com"
      },
      "skills": ["Python", "Machine Learning", "LangChain"],
      "jobSource": {
        "platform": "dice",
        "sourceName": "Dice",
        "sourceType": "job_board"
      }
    }
  ],
  "totalCount": 150,
  "page": 1,
  "totalPages": 6
}
```

## Notes

- Requires Dice account connected via MCP
- Rate limit: ~60 requests/minute
- Best for: Tech jobs, engineering positions
- Geographic coverage: US primarily

## Setup

1. Visit https://mcp.dice.com/mcp
2. Sign in with Dice account
3. Follow installation instructions
4. Verify with `claude mcp list`
