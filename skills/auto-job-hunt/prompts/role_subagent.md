# Role Subagent Prompt

## Purpose

Orchestrate job search for a single role across multiple sources (Dice + Indeed).

## Input

You receive:
- `role_name`: The target role (e.g., "AI/ML Engineer")
- `quantity`: Total jobs to find for this role
- `user_filters`: Dict with location, visa_status, work_mode, score_threshold
- `source_split`: How to split between sources (e.g., "50/50")
- `search_terms_per_source`: List of search terms to use (2-4 per source)
- `profile_path`: Path to role profile.md
- `scoring_path`: Path to role scoring.md

## Path Rules

Resolve all paths via `scripts/paths.py`. Do not hardcode absolute locations.

## Process

1. **Parse the distribution**:
   - Calculate jobs per source based on source_split
   - Calculate jobs per search term (quantity_per_source / num_terms)

2. **Launch source subagents in parallel**:
   - For Dice: Launch source_subagent with source="dice"
   - For Indeed: Launch source_subagent with source="indeed"

3. **Aggregate results**:
   - Collect scored jobs from both sources
   - Apply score threshold filter
   - Return final list of scored jobs

## Output

Return a list of jobs with:
- All job fields from the source
- `score`: 0-100
- `recommendation`: "Apply" / "Consider" / "Skip"
- `source`: "dice" or "indeed"
- `searchTerm`: Which search term found this job

## Example

```
Input:
  role_name: "AI/ML Engineer"
  quantity: 50
  user_filters: {location: "Boston", work_mode: "remote", score_threshold: 50}
  source_split: "50/50"
  search_terms_per_source: ["RAG LangChain", "Weaviate Qdrant", "LLM deployment", "AI Engineer"]

Output:
  [
    {
      "id": "...",
      "title": "AI/ML Engineer",
      "score": 78,
      "recommendation": "Apply",
      "source": "dice",
      "searchTerm": "RAG LangChain"
    },
    ...
  ]
```
