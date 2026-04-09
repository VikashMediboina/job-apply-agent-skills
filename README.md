# jobs-skill: Job Hunt Automation for AI Coding Agents

This bundle provides skills and commands for automated job searching, candidate profile generation, and application automation. It works with OpenCode, Claude Code, and other AI coding agents.

## Install OpenCode(Recommended) /Claude code (Required)

If you don't have OpenCode installed, follow these steps:

### Option 1: macOS (Homebrew)

```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install OpenCode
brew install opencode
```

### Option 2: macOS (Direct Download)

```bash
# Download the latest version
curl -L -o opencode.zip https://github.com/anomalyco/opencode/releases/latest/download/opencode-macos.zip

# Unzip
unzip opencode.zip

# Move to PATH
sudo mv opencode /usr/local/bin/

# Or to ~/bin/
mkdir -p ~/bin
mv opencode ~/bin/

# Add to PATH (add to ~/.zshrc or ~/.bashrc)
export PATH="$HOME/bin:$PATH"
```

### Option 3: Linux

```bash
# Download the latest version
curl -L -o opencode.tar.gz https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux.tar.gz

# Extract
tar -xzf opencode.tar.gz

# Move to PATH
sudo mv opencode /usr/local/bin/
```

### Verify OpenCode Installation

```bash
# Check version
opencode --version

# Should show something like: opencode v0.x.x
```

## Prerequisites

Before installing, ensure you have:

```bash
# Required tools
python3 --version   # >= 3.10
git --version
opencode --version  # latest
```

## Installation (Run one by one)

**Important:** Each step depends on the previous one complete successfully.

### Step 1: Install Playwright MCP (Required for flow-applicator)

Run the installer to auto-add Playwright MCP:

```bash
cd ~/jobs-skill
python3 scripts/install.py --mcp-only
```

Or manually add to your OpenCode config file:

```bash
code ~/.config/opencode/opencode.json
```

Add the Playwright MCP configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@anthropic/mcp-server-playwright"],
      "enabled": true
    }
  }
}
```

### Step 2: Verify Playwright MCP is attached

```bash
# Check if Playwright MCP is configured and attached
opencode mcp list

# Expected output should include: playwright
```

### Step 3: Authenticate Job Search MCPs (Optional for auto-job-hunt)

Authenticate with Dice and Indeed MCPs using the built-in auth command:

```bash
# Authenticate with Dice MCP
opencode mcp auth dice

# Authenticate with Indeed MCP
opencode mcp auth indeed

# List all MCPs and their auth status
opencode mcp auth list
```

Note: You may need a Dice/Indeed account for OAuth authentication.

Then verify:

```bash
# Verify all MCPs are authenticated
opencode mcp list
```

### Step 4: Verify Prerequisites

```bash
# Check Python
python3 --version

# Check git
git --version

# Check OpenCode is installed
opencode --version
```

### Step 5: Clone the Repository

```bash
# Clone this repo to get the install script
git clone https://github.com/VikashMediboina/job-apply-agent-skills.git ~/jobs-skill
cd ~/jobs-skill
```

Or if you already have it:

```bash
cd ~/jobs-skill
git pull
```

### Step 6: Run the Installer

```bash
# Navigate to the repo
cd ~/jobs-skill

# Dry run first to see what would be installed
python3 scripts/install.py --dry-run

# Run with global scope (recommended)
python3 scripts/install.py --scope global

# Or local scope
python3 scripts/install.py --scope local
```

The installer will:
1. Clone the repo to a temp location
2. Ask for scope (global or local)
3. Install skills to `~/.config/opencode/skills/` (global) or `./skills/` (local)
4. Install commands to `~/.config/opencode/commands/` (global) or `./commands/` (local)
5. Install flows to `~/.agents/skills/flow-applicator/flows/` (global) or `./skills/flow-applicator/flows/` (local)

### Step 7: Verify Installation

```bash
# Check skills were installed
ls ~/.config/opencode/skills/
# Should show: auto-job-hunt/  flow-applicator/  resume-profile-generator/

# Check commands were installed
ls ~/.config/opencode/commands/
# Should show: auto-job-hunt.md  apply-jobs.md  resume-profile.md

# Check flows were installed
ls ~/.agents/skills/flow-applicator/flows/
# Should show: greenhouse.json  lever.json  linkedin_easy_apply.json  ...
```

## Scope: Global vs Local

| Aspect | Global | Local |
|-------|-------|-------|
| Skills | `~/.config/opencode/skills/` | `./skills/` (workspace) |
| Commands | `~/.config/opencode/commands/` | `./commands/` (workspace) |
| Flows | `~/.agents/skills/flow-applicator/flows/` | `./skills/flow-applicator/flows/` |
| Use case | All your projects | Single project |

**Why it matters:** Global installs apply to every project. Local installs are project-specific and won't be shared.

**Choosing scope:**
- Use `global` for skills you want in all projects
- Use `local` for project-specific customizations

## Skills Usage

### 1. auto-job-hunt

Search Dice and Indeed for jobs matching your profile, score them, and export to markdown.

**When to use:**
- User says "find me jobs", "search for [role] jobs", "job hunt"
- You have a candidate profile and want qualified job listings

**How to invoke:**
```
Use the auto-job-hunt skill to search for jobs.
```

### ATS API Sources (New in v1.3.0)

The auto-job-hunt skill now includes **6 additional ATS API sources** for job scraping without requiring MCP:

| Source | Method | No Auth Required |
|--------|--------|------------------|
| Greenhouse | API | ✅ (39 company boards) |
| Lever | API | ✅ (30 company sites) |
| Ashby | GraphQL | ✅ (30 orgs) |
| Workable | API | ✅ (public board) |
| SmartRecruiters | API | ✅ (30 companies) |
| BambooHR | Embed | ✅ (25 subdomains) |

**Usage:**
```python
import sys
sys.path.insert(0, '.agents/skills/flow-applicator/scripts')
from ats_clients.greenhouse import GreenhouseClient
from ats_clients.lever import LeverClient
from ats_clients.ashby import AshbyClient
from ats_clients.workable import WorkableClient
from ats_clients.smartrecruiters import SmartRecruitersClient
from ats_clients.bamboohr import BambooHRClient

# Search jobs from any ATS
client = GreenhouseClient()
jobs = client.search_jobs(query='software engineer', location='remote', limit=30)

client = LeverClient()
jobs = client.search_jobs(query='engineer', location='remote', limit=20)

client = AshbyClient()
jobs = client.search_jobs(query='AI engineer', limit=20)

client = SmartRecruitersClient()
jobs = client.search_jobs('software engineer', location='remote', limit=20)

client = BambooHRClient()
jobs = client.search_jobs(query='engineer', location='remote', limit=20)
```

**Example 1: Search for data science jobs**
```
Find me data science jobs in San Francisco. Use auto-job-hunt with min score 70.
```

**Example 2: Search for remote DevOps roles**
```
Search for remote DevOps Engineer positions on Dice and Indeed. Min salary 120k.
```

**Example 3: Daily job scan**
```
Run today's job search. Score jobs using my full stack profile.
```

**Example 4: Search with salary filter**
```
Find Python developer jobs in NYC with salary 150k+. Use auto-job-hunt.
```

**Example 5: Both sources**
```
Search Dice and Indeed for machine learning engineer roles. Remote only.
```

### 2. flow-applicator

Automate job applications using reusable flow graphs for ATS platforms.

**When to use:**
- User says "apply to jobs", "submit applications", "run applications"
- You have a `jobs.md` file from auto-job-hunt
- Jobs are on Dice/LinkedIn/Greenhouse/Lever/Ashby/Workday

**New in v1.3.0:** The flow-applicator now supports **direct API submission** for 6 ATS platforms:
- Greenhouse API (no browser needed)
- Lever API (no browser needed)
- Ashby API (no browser needed)
- Workable API (no browser needed)
- SmartRecruiters API (no browser needed)
- BambooHR API (no browser needed)

**How to invoke:**
```
Use the flow-applicator skill to apply to jobs.
```

### /apply-jobs

Launches the flow-applicator skill directly.

```bash
/apply-jobs
# or
apply-jobs
```

**Example 1: Apply to today's jobs**
```
Apply to the qualified jobs from today's job search. Use flow-applicator.
```

**Example 2: Apply with min score**
```
Apply to jobs from 2026-04-07 using flow-applicator. Min score 80%.
```

**Example 3: Apply to specific company**
```
Apply to all qualified Google jobs using flow-applicator.
```

**Example 4: Dry run**
```
Show me the application plan for today's jobs. Don't apply yet.
```

### 3. resume-profile-generator

Extract resume text, analyze sections, generate candidate profiles with scoring criteria.

**When to use:**
- User provides a resume file (.pdf, .docx, .txt)
- You need structured candidate profiles for job matching
- You need search terms for job searching

**How to invoke:**
```
Use the resume-profile-generator skill to process resumes.
```

**Example 1: Parse a resume**
```
Process my resume at ~/documents/resume.pdf. Generate a candidate profile.
```

**Example 2: Multiple resumes**
```
Process all resumes in ~/applications/2026/. Generate candidate profiles for each.
```

**Example 3: Generate search terms**
```
Generate job search terms for a React Developer role based on my profile.
```

## Commands Usage

### /auto-job-hunt

Launches the auto-job-hunt skill directly.

```bash
/auto-job-hunt
# or
auto-job-hunt
```

**Example 1: Search with filters**
```
/auto-job-hunt role=DevOps Engineer location=Remote min_score=70
```

**Example 2: Dice only**
```
/auto-job-hunt source=dice role=Data Engineer
```

**Example 3: Export to CSV**
```
/auto-job-hunt format=csv output=jobs.csv
```

### /apply-jobs

Launches the flow-applicator skill to submit job applications.

```bash
/apply-jobs
# or
apply-jobs
```

**Example 1: Apply to today's jobs**
```
/apply-jobs date=today min_score=70
```

**Example 2: Apply to specific date**
```
/apply-jobs date=2026-04-07 min_score=80
```

**Example 3: Dry run**
```
/apply-jobs date=today dry_run=true
```

### /resume-profile

Launches the resume-profile-generator skill directly.

```bash
/resume-profile
# or
resume-profile
```

**Example 1: Process resume**
```
/resume-profile path=~/resume.pdf
```

**Example 2: Multiple roles**
```
/resume-profile path=~/resume.pdf roles="Full Stack Developer,Backend Engineer"
```

**Example 3: With Q&A answers**
```
/resume-profile path=~/resume.pdf auth=citizen mode=remote relocation=yes
```

## Interdependence

**Why run one by one:** These components depend on each other.

```
resume-profile-generator  →  auto-job-hunt  →  flow-applicator
       ↓                    ↓               ↓
  Candidate Profile   →  Jobs List    →  Applications
```

1. **resume-profile-generator** creates your candidate profile
2. **auto-job-hunt** uses the profile to find and score jobs
3. **flow-applicator** applies to the scored jobs

**Typical workflow:**

```
Step 1: Generate your profile
/resume-profile path=~/resume.pdf

Step 2: Find jobs
/auto-job-hunt role="Full Stack Developer"

Step 3: Apply
/auto-job-hunt   # First search
flow-applicator # Then apply
```

## File Structure

```
jobs-skill/
├── scripts/
│   ├── install.py          # Installation script
│   └── manifest.json     # Install configuration
├── commands/
│   ├── auto-job-hunt.md
│   ├── apply-jobs.md
│   └── resume-profile.md
├── skills/
│   ├── auto-job-hunt/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   ├── prompts/
│   │   ├── instincts/
│   │   └── sources/
│   ├── flow-applicator/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   ├── prompts/
│   │   └── instincts/
│   └── resume-profile-generator/
│       ├── SKILL.md
│       ├── scripts/
│       └── instincts/
└── flow-applicator/
    └── flows/
        ├── registry.json
        ├── greenhouse.json
        ├── lever.json
        ├── linkedin_easy_apply.json
        └── ...
```

## Troubleshooting

### MCP not connected

```bash
# Authenticate MCP servers
opencode mcp auth dice
opencode mcp auth indeed

# Verify
opencode mcp list
```

### Permission errors

```bash
# Check permissions
ls -la ~/.config/opencode/
ls -la ~/.agents/

# Fix if needed
chmod 755 ~/.config/opencode
chmod 755 ~/.agents
```

### Reinstall

```bash
# Force reinstall
python3 scripts/install.py --force --scope global
```

### Verify skills load

```bash
# Test skill detection
opencode --skills
```

## Uninstall

```bash
# Remove global installations
rm -rf ~/.config/opencode/skills/auto-job-hunt
rm -rf ~/.config/opencode/skills/flow-applicator
rm -rf ~/.config/opencode/skills/resume-profile-generator
rm -rf ~/.config/opencode/commands/auto-job-hunt.md
rm -rf ~/.config/opencode/commands/apply-jobs.md
rm -rf ~/.config/opencode/commands/resume-profile.md
rm -rf ~/.agents/skills/flow-applicator/flows/

# Remove local installations (from workspace)
rm -rf skills/auto-job-hunt
rm -rf skills/flow-applicator
rm -rf skills/resume-profile-generator
rm -rf commands/auto-job-hunt.md
rm -rf commands/apply-jobs.md
rm -rf commands/resume-profile.md
```

## Quick Reference

| Command | Action |
|---------|--------|
| `python3 scripts/install.py --dry-run` | Preview install |
| `python3 scripts/install.py --scope global` | Install globally |
| `python3 scripts/install.py --scope local` | Install locally |
| `python3 scripts/install.py --force` | Overwrite existing |

| Trigger | Skill |
|---------|-------|
| "find jobs", "search jobs" | auto-job-hunt |
| "apply to jobs" | flow-applicator |
| "process resume", "profile" | resume-profile-generator |

| Scope | Location |
|------|----------|
| Global | `~/.config/opencode/` |
| Local | `./` (workspace) |

---

## Contributing

We welcome contributions! Here's how to contribute to this project.

### Ways to Contribute

1. **Report bugs** - Found an issue? Let us know
2. **Suggest features** - Have an idea? Share it
3. **Add new skills** - Extend the automation
4. **Improve flows** - Add new ATS platforms
5. **Fix documentation** - Help others get started

### How to Submit Contributions

**Step 1: Check Existing Issues**

Before creating a new issue, check if it's already reported:

```bash
# View existing issues
open https://github.com/VikashMediboina/job-apply-agent-skills/issues
```

**Step 2: Create an Issue**

For bugs:

```markdown
## Bug Report

**Description:**
[What happened]

**Steps to reproduce:**
1. [Step 1]
2. [Step 2]

**Expected:**
[What should happen]

**Actual:**
[What happened]

**Environment:**
- OS: [e.g., macOS 14]
- OpenCode version: [e.g., v0.1.50]
```

For feature requests:

```markdown
## Feature Request

**Feature name:**
[Name]

**Use case:**
[Why do you need this?]

**Proposed solution:**
[How should it work?]
```

**Step 3: Submit a Pull Request**

For code contributions:

```bash
# 1. Fork the repo
open https://github.com/VikashMediboina/job-apply-agent-skills/fork

# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/opencode.git ~/jobs-skill
cd ~/jobs-skill

# 3. Create a branch
git checkout -b feature/my-feature

# 4. Make changes
# ... edit files ...

# 5. Commit and push
git add .
git commit -m "Add: description"
git push origin feature/my-feature

# 6. Create PR
open https://github.com/VikashMediboina/job-apply-agent-skills/compare
```

### Contribution Guidelines

- **Run tests** before submitting:
  ```bash
  python3 scripts/install.py --dry-run
  ```

- **Follow existing code style** - Match the patterns in the codebase

- **Update documentation** - Include README changes with PRs

- **Test locally** before submitting:
  ```bash
  # Test MCP install
  python3 scripts/install.py --mcp-only --dry-run
  
  # Test skill install
  python3 scripts/install.py --dry-run --scope local
  ```

### Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Help others learn and grow
- Focus on what's best for the community

### Recognition

Contributors will be acknowledged in the project.

---

## Getting Help

- **Documentation** - Start with this README
- **Issues** - Report bugs at https://github.com/VikashMediboina/job-apply-agent-skills/issues
- **Discussions** - Ask questions at https://github.com/VikashMediboina/job-apply-agent-skills/discussions
