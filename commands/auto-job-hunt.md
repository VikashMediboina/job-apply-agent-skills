---
name: auto-job-hunt
description: Launch the auto-job-hunt skill to search, score, and export jobs from Dice and Indeed.
allowed_tools: ["Read", "Write", "Glob", "Question", "Task"]
---

# /auto-job-hunt - Auto Job Hunt

This command is only a launcher. All behavior lives in `skills/auto-job-hunt`.

When invoked, load and follow the `auto-job-hunt` skill end-to-end:
- validate profile and role bundle files
- validate Dice and Indeed MCP connectivity
- parse roles, quantity, timeline, and filters
- plan Dice/Indeed/search-term distribution
- score jobs using the role-specific criteria
- write markdown files with proper segregation:
  - `{repo_root}/jobs/{date}/{timestamp}/jobs.md` - All jobs (Apply/Consider segregated)
  - `{repo_root}/jobs/{date}/{timestamp}/index.md` - Summary index
- write `{repo_root}/jobs/status/{date}/{timestamp}.md`
- cleanup `{workspace_root}/temp/`

Do not duplicate workflow details here.
