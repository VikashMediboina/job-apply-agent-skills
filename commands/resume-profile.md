---
name: resume-profile
description: Launch the resume-profile-generator skill to process resumes and build candidate profiles.
allowed_tools: ["Read", "Write", "Glob", "Question", "Task"]
---

# /resume-profile - Resume Profile Generator

This command is only a launcher. All behavior lives in `resume-profile-generator`.

When invoked, load and follow the `resume-profile-generator` skill end-to-end:
- extract resume text with the bundled Python script
- analyze the resume section by section
- infer roles from the recent timeline
- ask missing mandatory questions
- generate candidate folders, profiles, scoring, and search terms

Do not duplicate workflow details here.
