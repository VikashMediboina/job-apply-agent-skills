---
name: resume-profile-generator
description: Analyzes resumes to generate structured candidate profiles with scoring criteria and job search terms. Supports multiple resumes with user-level and role-specific data. Use when user provides resumes for job application preparation.
---

# Resume Profile Generator

## Overview

This skill processes one or more resumes to create structured candidate profiles with scoring criteria and job search terms. It extracts text from PDF/DOCX/TXT, runs section-by-section analysis, infers target roles from the candidate's recent timeline (not assumptions), confirms with the user, then generates profiles, scoring, and search terms.

## When to Use

- User provides a resume or multiple resumes for job application preparation
- User wants to extract structured profile data from resume files
- User needs scoring criteria to evaluate job matches
- User needs search terms for finding relevant job postings

## When NOT to Use

- User already has a structured profile in another format
- User wants manual entry without a resume file

---

## Workflow

### Phase 1: Resume Intake & Text Extraction

1. Accept resume via uploaded file or file path (.pdf, .docx, .txt)
2. Run the extraction script to get raw text:

```bash
python3 skills/resume-profile-generator/scripts/extract_resume.py "<resume_path>" --sections -o "<output_path>"
```

The script:
- Tries **pdfplumber** first for PDFs (best layout), falls back to **pdfminer**, then **PyPDF2**
- Extracts **DOCX** via python-docx, preserving heading styles and table content
- Passes through **.txt** files directly
- Detects and splits resume sections automatically (experience, education, skills, projects, etc.)
- Returns both raw text and a structured `{sections}` JSON

3. Save extracted text to a temporary working file for analysis only
4. Save the original file path and resume location in the generated markdown outputs
5. Do not keep `resume.md` in the final candidate folder

### Phase 2: Section-by-Section LLM Analysis

Feed the extracted text to the LLM in structured passes. Do NOT try to understand the entire resume at once. Analyze each section independently, then synthesize.

**Pass 1 — Contact & Identity:**
Extract from the contact/header section:
- Full name
- Email, phone
- Location (city, state, country)
- LinkedIn URL
- GitHub / portfolio URL

**Pass 2 — Work Experience Timeline:**
Extract a chronological timeline from the experience section:
```
[
  {
    "company": "Company Name",
    "title": "Job Title",
    "start": "YYYY-MM",
    "end": "YYYY-MM or Present",
    "technologies": ["tech1", "tech2"],
    "domain": "industry/domain",
    "responsibilities": ["key responsibility 1", "key responsibility 2"]
  }
]
```
Sort by date descending (most recent first). This timeline drives role inference.

**Pass 3 — Education:**
Extract:
- Degree, field of study, institution, year
- Relevant coursework
- Academic projects
- GPA (if listed)

**Pass 4 — Skills Inventory:**
Extract all listed skills and categorize:
- Programming languages
- Frameworks / libraries
- Tools / platforms
- Cloud / infrastructure
- Databases
- Soft skills
- Domain expertise

**Pass 5 — Projects:**
Extract project entries:
- Project name, description
- Technologies used
- Outcome / impact
- Link (if provided)

**Pass 6 — Certifications / Awards / Other:**
Extract any remaining sections.

### Phase 3: Timeline-Based Role Inference

**CRITICAL: Do NOT assume or pre-decide a role. Analyze the candidate's RECENT work timeline to determine what roles they are actually qualified for.**

Rules for role inference:
1. Look at the **most recent 2-3 positions** (last 2-3 years)
2. Identify the **technologies actively used** in those positions
3. Identify the **domain/industry** of those positions
4. Map to concrete role titles based on what they **actually did**, not what their title was
5. Consider the **trajectory** — are they moving toward a specific direction?

Example logic:
```
IF most_recent_role uses [Python, AWS, Terraform, Docker] in last 12 months
  AND previous_role used [Python, Jenkins, Ansible]
  THEN suggest: "DevOps Engineer", "Cloud Engineer", "Site Reliability Engineer"

IF most_recent_role uses [React, TypeScript, Next.js] in last 12 months
  AND has [Node.js, PostgreSQL] in skills
  THEN suggest: "Full Stack Developer", "Frontend Engineer", "React Developer"

IF most_recent_role is "Data Analyst" using [SQL, Python, Tableau]
  AND has [ML coursework, TensorFlow in projects]
  THEN suggest: "Data Analyst", "Business Intelligence Analyst", "Junior Data Scientist"
```

**Present suggested roles to the user and ask them to confirm, modify, or add roles.**

Use the question tool:
```
Based on your recent experience at [Company] as [Title] working with [Tech1, Tech2, Tech3],
and your previous role at [Company2] as [Title2], I suggest these target roles:

1. [Role 1] — because you've been actively using [tech] in [domain]
2. [Role 2] — because your trajectory shows [pattern]
3. [Role 3] — because you have [skill] + [domain] combination

Confirm these roles, or tell me which to change/add.
```

### Phase 4: Mandatory Questions (Missing Info)

After extraction and role confirmation, ask only what is missing from the resume. Use the ask-questions-if-underspecified approach:

**Must-have (block until answered):**

```text
Need to know:

1) Work authorization?
   a) US Citizen / Green Card (no sponsorship needed)
   b) STEM OPT — is sponsorship mandatory? Expiry date?
   c) H1B — is transfer possible? Expiry date?
   d) OPT (pre-STEM) — sponsorship timeline?
   e) Other: ___

2) Sponsorship requirement?
   a) No sponsorship needed
   b) Need sponsorship in future (when?)
   c) Need sponsorship now
   d) H1B transfer only

3) Work mode preference?
   a) Remote only
   b) Hybrid OK
   c) Onsite OK
   d) Flexible (any)

4) Location?
   a) Current city only
   b) Willing to relocate (where?)
   c) Fully remote — location doesn't matter

5) Notice period?
   a) Immediate
   b) 2 weeks
   c) 1 month
   d) Other: ___

Reply with: 1a 2a 3d 4c 5b (or type answers)
```

**Nice-to-have (default if not provided):**
- Expected salary range (default: "Market rate")
- Employment type (default: "Full-time")
- LinkedIn/GitHub (default: "Not provided")

### Phase 5: Folder Structure & File Generation

For each candidate, create:

```
First_Last/
├── index.md                    # Entry point, links to roles
├── profile.md                  # Master user-level profile
├── user_qna.md                 # User-level Q&A answers
└── <RoleName>/
    ├── pdf/
    │   └── resume.pdf          # Original resume copy for this role
    ├── profile.md              # Role-specific skills/projects/experience overlay
    ├── scoring.md              # Job matching scoring criteria
    ├── searchterms.md          # Job search terms (broad/medium/narrow)
    └── role_qna.md             # Role-specific Q&A answers
```

### Phase 6: Generate User-Level Profile

**profile.md:**
```markdown
# Candidate Profile: [Full Name]

## Basic Information
- Name: [Full Name]
- Email: [Email]
- Phone: [Phone]
- Location: [City, State, Country]
- LinkedIn: [URL]
- GitHub/Portfolio: [URL]
- Current Location: [City, State, Country]
- Years of Experience: [X years]

## Work Authorization
- Authorized to work in US: [Yes/No]
- Visa sponsorship required: [Now/Future/No]
- Current status: [Citizen/GC/OPT/STEM OPT/H1B/Other]
- Expiration date: [Date or N/A]

## Preferences
- Work mode: [Remote/Hybrid/Onsite/Flexible]
- Willing to relocate: [Yes/No — where]
- Employment type: [Full-time/Contract/C2H/W2]
- Expected salary: [Range or Market rate]
- Notice period: [Duration]
- Available start: [Date]

## Work Timeline (Most Recent First)

| Period | Company | Title | Key Technologies | Domain |
|--------|---------|-------|-----------------|--------|
| YYYY-MM — Present | Company | Title | Tech1, Tech2 | Domain |
| YYYY-MM — YYYY-MM | Company | Title | Tech1, Tech2 | Domain |

## Target Roles
1. [Role 1] — rationale
2. [Role 2] — rationale
3. [Role 3] — rationale
```

**user_qna.md:**
```markdown
# User-Level Q&A

Q: What is your current work authorization status?
A: [Answer]

Q: Do you require visa sponsorship?
A: [Answer — Now/Future/No + details]

Q: What is your preferred work mode?
A: [Answer]

Q: What is your current location?
A: [Answer]

Q: Are you willing to relocate?
A: [Answer]

Q: What is your notice period?
A: [Answer]

Q: When can you start?
A: [Answer]

Q: What is your expected salary range?
A: [Answer]
```

### Phase 7: Generate Role-Specific Files

For EACH confirmed role, create a subfolder and generate:

**RoleName/profile.md:**
```markdown
# Role Profile: [Role Name]

## Relevant Skills
- Primary: [skills most relevant to this role from skills inventory]
- Secondary: [supporting skills]
- Missing/Growth: [skills the candidate should highlight or develop]

## Relevant Projects
- [Project]: [why relevant to this role]

## Relevant Experience
- [Company/Title]: [specific responsibilities relevant to this role]

## Industry Experience
- [Industry]: [years] — [relevance to role]

## Education Relevance
- [Degree/Coursework]: [relevance to role]

## Candidate Strengths for This Role
1. [Strength 1]
2. [Strength 2]

## Potential Gaps
1. [Gap 1] — [mitigation strategy]
```

**RoleName/scoring.md:**
```markdown
# Scoring Criteria: [Role Name]

## Weight Distribution

### User-Level Fit (60%)
| Factor | Weight | Scoring Logic |
|--------|--------|---------------|
| Work authorization match | 20% | Citizen/GC=100%, H1B transfer=80%, OPT+sponsorship=70%, Needs sponsorship=50% |
| Visa sponsorship fit | 15% | No sponsorship needed=100%, Future=70%, Now=50%, Mismatch=0% |
| Location/relocation fit | 10% | Exact match=100%, Metro=80%, State=60%, Relocate=50%, Remote=100% |
| Work mode fit | 10% | Exact match=100%, Partial=70%, Mismatch=0% |
| Salary expectation fit | 5% | Within range=100%, Within 10%=80%, Over 20%=40% |

### Role-Level Fit (40%)
| Factor | Weight | Scoring Logic |
|--------|--------|---------------|
| Skills match | 15% | Count matching required skills / total required |
| Recent experience relevance | 10% | Last 2 years doing similar work=100%, 3-5 years=70%, 5+ years ago=40% |
| Industry/domain match | 5% | Same industry=100%, Adjacent=60%, Different=30% |
| Education fit | 5% | Meets requirement=100%, Close=70%, Unrelated=40% |
| Years of experience | 5% | Within range=100%, Under by 1-2=70%, Over=90%, Under by 3+=40% |

## Application Recommendation
- **Apply**: Score >= 70%
- **Consider**: Score >= 50%
- **Skip**: Score < 50%

## Red Flags (Auto-Skip)
- Visa sponsorship required AND role explicitly says "No sponsorship"
- Location mismatch AND not willing to relocate AND not remote
- Salary expectation > 30% above role range
- Missing 3+ required skills with no adjacent experience
```

**RoleName/searchterms.md:**
```markdown
# Job Search Terms: [Role Name]

## Broad Search (Set 1) — High volume, cast wide net
- [Primary role title] jobs
- [Alternative title 1] positions
- [Key skill 1] [Key skill 2] developer
- [Industry] [role type] jobs

## Medium Search (Set 2) — Balanced targeting
- "[Exact role title]" [location or "remote"]
- [Skill 1] AND [Skill 2] [role type]
- [Company type] [role title] -[exclusion]
- "[Framework]" "[Language]" engineer

## Narrow Search (Set 3) — Precision matches
- "[Skill 1]" "[Skill 2]" "[Skill 3]" [role]
- "[Specific domain]" [role] [seniority level]
- site:linkedin.com/jobs "[role title]" "[key technology]"

## Alternative Job Titles
1. [Title 1]
2. [Title 2]
3. [Title 3]
4. [Title 4]

## Platform-Specific Queries
- **LinkedIn**: [optimized LinkedIn search string]
- **Indeed**: [optimized Indeed search string]
- **Dice**: [optimized Dice search string]

## Recommended Filters
- Experience: [Entry/Mid/Senior]
- Work type: [Remote/Hybrid/Onsite]
- Salary: [$min - $max]
- Date posted: Last [7/14/30] days
- Location: [City/State or Remote]
```

**RoleName/role_qna.md:**
```markdown
# Role-Specific Q&A: [Role Name]

Q: What are your key technical skills for this role?
A: [Extracted from skills inventory, filtered for role relevance]

Q: Which projects demonstrate relevant experience?
A: [Extracted from projects section, filtered for role relevance]

Q: What industry experience aligns with this role?
A: [Extracted from timeline, filtered for role relevance]

Q: Describe your most recent relevant work.
A: [From most recent matching position in timeline]

Q: What is your target job title?
A: [The confirmed role name]

Q: What seniority level are you targeting?
A: [Inferred from years + trajectory]
```

### Phase 8: Generate Index Files

**First_Last/index.md:**
```markdown
# [Full Name] — Candidate Index

## Profile Summary
- Location: [City, State, Country]
- Work Auth: [Status] | Sponsorship: [Yes/No]
- Experience: [X years]
- Work Mode: [Preference]

## Target Roles

| Role | Profile | Scoring | Search Terms |
|------|---------|---------|--------------|
| [Role 1] | [profile.md](./Role1/profile.md) | [scoring.md](./Role1/scoring.md) | [searchterms.md](./Role1/searchterms.md) |
| [Role 2] | [profile.md](./Role2/profile.md) | [scoring.md](./Role2/scoring.md) | [searchterms.md](./Role2/searchterms.md) |

## Files
- [Master Profile](./profile.md)
- [User Q&A](./user_qna.md)
```

**Top-level index (if multiple candidates):**
```markdown
# Candidate Profiles Index

| Name | Target Roles | Location | Work Auth | Sponsorship | Profile |
|------|-------------|----------|-----------|-------------|---------|
| [Name] | [Role1, Role2] | [City, State] | [Status] | [Yes/No] | [index](./First_Last/index.md) |
```

---

## Multi-Resume Handling

When processing multiple resumes:

1. Main agent accepts all resume paths/uploads
2. For each resume, launch a **parallel subagent** that:
    - Runs extraction script
    - Does section-by-section analysis
    - Returns extracted data + suggested roles
3. Main agent collects all results
4. Main agent asks user-level questions ONCE per candidate (batch if same person with multiple resumes)
5. Main agent confirms roles for ALL candidates
6. Main agent dispatches parallel subagents to generate folder structures
7. Main agent creates top-level index linking everything

When generating final files, keep `resume.md` only as a temporary working artifact. Remove it after the profiles are written.

For each confirmed role, store a copy of the resume PDF under `First_Last/<RoleName>/pdf/resume.pdf`.

If same name appears in multiple resumes:
- Ask user to disambiguate
- Or create numbered folders: `John_Smith_1/`, `John_Smith_2/`

---

## Extraction Script Reference

Location: `skills/resume-profile-generator/scripts/extract_resume.py`

```bash
# Basic extraction (text to stdout)
python3 scripts/extract_resume.py /path/to/resume.pdf

# Extract with section detection (JSON output)
python3 scripts/extract_resume.py /path/to/resume.pdf --sections

# Extract to file
python3 scripts/extract_resume.py /path/to/resume.pdf -o First_Last/resume.md

# Extract with sections to file
python3 scripts/extract_resume.py /path/to/resume.pdf --sections -o First_Last/resume_sections.json
```

Supported formats: `.pdf`, `.docx`, `.txt`
PDF extraction chain: pdfplumber -> pdfminer -> PyPDF2

---

## Error Handling

- **Invalid file format**: Ask user for PDF/DOCX/TXT
- **Cannot extract text**: Copy file as-is, note extraction failed, ask user to paste text manually
- **Missing critical info**: Ask mandatory questions before proceeding
- **Duplicate candidate**: Ask user to confirm or merge
- **Empty sections**: Note as "Not found in resume" rather than guessing

---

## Best Practices

1. NEVER assume a role — infer from recent timeline, confirm with user
2. Always ask mandatory visa/sponsorship questions if not clear from resume
3. Analyze sections independently before synthesizing
4. Use the most recent 2-3 positions for role inference, not the entire history
5. Default to broad search terms; include all three sets
6. Score jobs using weighted criteria combining user-level and role-level fit
7. Store original resume file alongside extracted text
8. For multiple resumes, process in parallel with subagents

---

## File Naming Convention

- Candidate folder: `First_Last` (capitalized, underscore separator)
- Role folder: `RoleName` (CamelCase, no spaces)
- Files: lowercase (profile.md, scoring.md, searchterms.md, role_qna.md, user_qna.md)
- Index: index.md in each candidate folder
