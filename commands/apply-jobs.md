---
name: apply-jobs
description: Launch the flow-applicator skill to submit applications for qualified jobs.
allowed_tools: ["Read", "Write", "Glob", "Question", "Task"]
---

# /apply-jobs - Job Application Automation

This command is only a launcher. All behavior lives in `flow-applicator`.

When invoked, load and follow the `flow-applicator` skill end-to-end:
- parse `jobs.md` and build a session plan
- detect ATS platforms and load matching flows
- fill forms, handle deviations, and submit applications
- record outcomes and update application history

Do not duplicate workflow details here.
