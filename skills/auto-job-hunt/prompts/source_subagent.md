# Source Subagent Prompt

## Purpose

Search one job board (Dice or Indeed) using multiple search terms.

## Input

You receive:
- `source`: "dice" or "indeed"
- `role_name`: The target role
- `search_terms`: List of 2-4 search terms to execute
- `quantity_per_source`: Total jobs to fetch from this source
- `scoring_path`: Path to scoring.md for this role
- `profile_path`: Path to profile.md for this role
- `user_filters`: Dict with location, visa_status, work_mode, etc.

## Path Rules

Write source outputs under `workspace_root()/temp/{source}/{role_name}/...`.

## Process

1. **Calculate jobs per term**:
   - quantity_per_source divided by number of search_terms
   - Typically 5-10 jobs per term

2. **Launch search term subagents in parallel**:
   - For each search_term in search_terms:
     - Launch search_term_subagent with:
       - search_term
       - source
       - quantity_per_term
       - scoring_path
       - profile_path
       - user_filters

3. **Aggregate results from all terms**:
   - Combine jobs from all search terms
   - Remove duplicates (same job from different terms)
    - Save to `workspace_root()/temp/{source}/{role_name}/jobs.md`

4. **Return aggregated jobs**:
   - Each job should have score, recommendation, searchTerm fields

## MCP Usage

### For Dice:
Use the Dice MCP `job_search` tool:
```
job_search(
  query: "<search_term>",
  location: <user_filters.location>,
  remote: <user_filters.work_mode == "remote">,
  posted: "<24h or 7d>",
  jobType: "fulltime",
  count: <quantity_per_term>
)
```

### For Indeed:
Use the Indeed MCP `job_search` tool:
```
job_search(
  query: "<search_term>",
  location: <user_filters.location>,
  remote: <user_filters.work_mode == "remote">,
  posted: "<24h or 7d>",
  jobType: "fulltime",
  count: <quantity_per_term>
)
```

## Output Format

Save to: `workspace_root()/temp/{source}/{role_name}/jobs.md`

```markdown
# {source} Jobs: {role_name}

Total: {count} jobs

## Job List

### 1. {job_title}
- **Company**: {company_name}
- **Location**: {city}, {state} ({work_type})
- **Score**: {score}/100 - {recommendation}
- **Search Term**: {search_term}
- **Apply URL**: {apply_url}
...
```

## Example

```
Input:
  source: "dice"
  role_name: "AI/ML Engineer"
  search_terms: ["RAG LangChain", "Weaviate Qdrant", "LLM deployment"]
  quantity_per_source: 25
  scoring_path: "/path/to/AIMLEngineer/scoring.md"
  profile_path: "/path/to/AIMLEngineer/profile.md"
  user_filters: {location: "Boston", work_mode: "remote"}

Process:
  - Term 1 "RAG LangChain": 8 jobs
  - Term 2 "Weaviate Qadrant": 8 jobs
  - Term 3 "LLM deployment": 9 jobs
  - Total: 25 jobs (some may be duplicates)

Output:
  - 20 unique scored jobs saved to `workspace_root()/temp/dice/AIMLEngineer/jobs.md`
  - Return list of jobs with scores
```
