# Agent-Spend GitHub Intelligence Tool

A Python scraper that finds **high-intent leads** for Natural by identifying developers who are actively building AI agent + payment integrations on GitHub.

## What It Does

1. **Searches GitHub** for repos that use agentic AI libraries (LangChain, CrewAI, AutoGPT, LangGraph, AutoGen) **combined with** payment libraries (Stripe, Plaid, Braintree, Square, Adyen)
2. **Filters** to high-signal repos — 10+ stars, updated in the last 30 days
3. **Enriches** each result with owner emails, LinkedIn/X profiles, and project context from the README
4. **Analyzes gaps** — detects patterns like hardcoded API keys in agent loops, manual payment orchestration, or DIY subscription billing
5. **Outputs `natural_top_leads.csv`** — a ranked list of up to 100 leads with technical proof of why they need Natural

## How It Helps the Team

- **GTM-in-a-box** — Hands the CEO a curated list of people currently struggling with the exact problem Natural solves
- **Technical proof, not guesswork** — Each lead comes with the specific agentic + payment tech they're using, the gap in their approach, and a suggested Natural pitch angle
- **Saves weeks of manual research** — Automates what would otherwise be hours of GitHub browsing and LinkedIn hunting
- **Prioritized by signal** — Leads are ranked by stars (proxy for traction), so the team focuses on the highest-value prospects first

## Output CSV Columns

| Column | What It Contains |
|--------|-----------------|
| Startup/Project | Name from the repo's README |
| Repo URL | Direct link to the repo |
| Stars / Last Updated | Traction & recency signals |
| Agentic Tech Found | e.g. `langchain, crewai` |
| Payment Tech Found | e.g. `stripe, plaid` |
| The Gap | Why their current approach is fragile |
| Natural's Play | 1-line pitch tailored to their stack |
| Owner Email / LinkedIn/X | Contact info for outreach |

## How to Run

```powershell
# Set token (PowerShell)
$env:GITHUB_TOKEN = "ghp_your_token"

# Or create a .env file with: GITHUB_TOKEN=ghp_your_token

python agent_spend_scraper.py
```

Takes ~15–30 min due to GitHub rate limits. Outputs `natural_top_leads.csv` in the same folder.
