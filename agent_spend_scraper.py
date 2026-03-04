"""
Agent-Spend GitHub Intelligence Tool
=====================================
Finds GitHub repos combining agentic AI libraries (LangChain, CrewAI, AutoGPT, etc.)
with payment libraries (Stripe, Plaid, Braintree, etc.) to generate a GTM lead list.

Usage:
    1. Set GITHUB_TOKEN environment variable with a GitHub Personal Access Token
    2. Run: python agent_spend_scraper.py
    3. Output: natural_top_leads.csv
"""

import os
import re
import csv
import sys
import time
import json
import base64
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

# ─── Configuration ───────────────────────────────────────────────────────────


def _load_token() -> str:
    """Load GitHub token from env var or .env file."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    # Fallback: read from .env file in the same directory as this script
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


GITHUB_TOKEN = _load_token()
BASE_URL = "https://api.github.com"
OUTPUT_FILE = "natural_top_leads.csv"
MAX_LEADS = 100
MIN_STARS = 10
DAYS_RECENT = 30

# Agentic AI libraries to search for
AGENTIC_LIBS = [
    "langchain",
    "crewai",
    "autogpt",
    "langgraph",
    "autogen",
    "llama_index",
    "llama-index",
    "openai-agents",
    "smolagents",
]

# Payment / fintech libraries to search for
PAYMENT_LIBS = [
    "stripe",
    "plaid",
    "braintree",
    "square",
    "adyen",
]

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agent-spend")


# ─── GitHub API Helpers ──────────────────────────────────────────────────────

def _headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _rate_limit_wait(response: requests.Response):
    """Respect GitHub rate limits by sleeping when necessary."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
    if remaining <= 1:
        reset_ts = int(response.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset_ts - int(time.time()), 0) + 2
        log.warning("Rate limit nearly exhausted – sleeping %ds …", wait)
        time.sleep(wait)


def github_get(url: str, params: dict = None) -> dict | None:
    """Make a GET request to the GitHub API with automatic rate-limit handling."""
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        except requests.RequestException as exc:
            log.error("Request failed: %s (attempt %d/3)", exc, attempt + 1)
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            _rate_limit_wait(resp)
            return resp.json()
        elif resp.status_code == 403:
            _rate_limit_wait(resp)
            time.sleep(5)
        elif resp.status_code == 422:
            log.warning("Validation error for %s: %s", url, resp.text[:200])
            return None
        else:
            log.warning("HTTP %d for %s (attempt %d/3)", resp.status_code, url, attempt + 1)
            time.sleep(2 ** attempt)
    return None


# ─── Step 1: Search GitHub for repos ────────────────────────────────────────

def build_search_queries() -> list[str]:
    """Generate code-search queries pairing each agentic lib with each payment lib."""
    queries = []
    for agent_lib in AGENTIC_LIBS:
        for pay_lib in PAYMENT_LIBS:
            queries.append(f"{agent_lib} {pay_lib}")
    return queries


def search_code(query: str, page: int = 1) -> list[dict]:
    """Run a GitHub code search and return matching items."""
    params = {
        "q": query,
        "per_page": 30,
        "page": page,
    }
    data = github_get(f"{BASE_URL}/search/code", params)
    if data and "items" in data:
        return data["items"]
    return []


def search_repos_via_code() -> dict:
    """
    Search for code files containing agentic + payment library imports.
    Returns a dict of repo_full_name -> {'agentic': set, 'payment': set, 'repo_data': dict}
    """
    queries = build_search_queries()
    repo_map: dict[str, dict] = {}
    total_queries = len(queries)

    log.info("Running %d search queries …", total_queries)

    for idx, query in enumerate(queries, 1):
        log.info("  [%d/%d] Searching: %s", idx, total_queries, query)
        
        # GitHub code search is heavily rate-limited; pause between queries
        time.sleep(6)  # GitHub requires 5s+ between code search requests

        items = search_code(query)
        if not items:
            continue

        parts = query.split()
        agent_lib = parts[0]
        pay_lib = parts[1]

        for item in items:
            repo = item.get("repository", {})
            full_name = repo.get("full_name", "")
            if not full_name:
                continue

            if full_name not in repo_map:
                repo_map[full_name] = {
                    "agentic": set(),
                    "payment": set(),
                    "repo_data": repo,
                }
            repo_map[full_name]["agentic"].add(agent_lib)
            repo_map[full_name]["payment"].add(pay_lib)

    log.info("Found %d unique repos from code search.", len(repo_map))
    return repo_map


# ─── Step 2: Filter & Enrich ────────────────────────────────────────────────

def get_repo_details(full_name: str) -> dict | None:
    """Fetch full repository metadata."""
    return github_get(f"{BASE_URL}/repos/{full_name}")


def get_readme_text(full_name: str) -> str:
    """Fetch and decode the README of a repo."""
    data = github_get(f"{BASE_URL}/repos/{full_name}/readme")
    if data and "content" in data:
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""


def get_contributors(full_name: str, limit: int = 5) -> list[dict]:
    """Fetch top contributors for a repo."""
    data = github_get(f"{BASE_URL}/repos/{full_name}/contributors", {"per_page": limit})
    if isinstance(data, list):
        return data
    return []


def get_user_details(username: str) -> dict | None:
    """Fetch a GitHub user's profile."""
    return github_get(f"{BASE_URL}/users/{username}")


def extract_company_from_readme(readme: str) -> str:
    """Try to pull a company/project name from the first few lines of a README."""
    lines = readme.strip().split("\n")
    for line in lines[:10]:
        line = line.strip().lstrip("#").strip()
        if line and len(line) < 100:
            # Skip badges / images
            if line.startswith("!") or line.startswith("[!") or line.startswith("<"):
                continue
            return line
    return ""


def extract_emails_from_text(text: str) -> list[str]:
    """Find email addresses in arbitrary text."""
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    emails = re.findall(pattern, text)
    # Filter out common false positives
    ignore_domains = {"example.com", "email.com", "domain.com", "your-email.com"}
    return [e for e in emails if e.split("@")[1].lower() not in ignore_domains]


def detect_gap(readme: str, agentic_libs: set, payment_libs: set) -> tuple[str, str]:
    """
    Heuristic gap analysis and Natural's play suggestion based on code/readme content.
    Returns (gap_description, naturals_play).
    """
    readme_lower = readme.lower()
    gap = ""
    play = ""

    # Pattern: hardcoded API keys
    if any(kw in readme_lower for kw in ["api_key", "api key", "secret_key", "sk_live", "sk_test"]):
        gap = "Likely using hardcoded API keys in agent payment loop."
        play = "Natural's secure tokenized payment infra removes key-exposure risk from autonomous agents."
    # Pattern: manual payment orchestration
    elif any(kw in readme_lower for kw in ["payment_intent", "paymentintent", "charge.create"]):
        gap = "Manually orchestrating payment intents inside agent code."
        play = "Natural's agent-native payment SDK handles intent lifecycle, retries, and escrow automatically."
    # Pattern: subscription management
    elif any(kw in readme_lower for kw in ["subscription", "recurring", "billing"]):
        gap = "Building custom subscription/billing logic for AI agents."
        play = "Natural's managed billing rails let agents handle recurring payments without custom plumbing."
    # Pattern: multi-provider
    elif len(payment_libs) > 1:
        gap = f"Integrating multiple payment providers ({', '.join(payment_libs)}) manually."
        play = "Natural unifies payment providers behind a single agent-friendly API."
    # Fallback
    else:
        gap = "Building agent-to-payment integrations from scratch without dedicated infra."
        play = "Natural provides purpose-built payment infrastructure for autonomous AI agents."

    return gap, play


# ─── Step 3: Build Lead List ────────────────────────────────────────────────

def build_leads(repo_map: dict) -> list[dict]:
    """Enrich repos with metadata and build the final lead list."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_RECENT)
    leads: list[dict] = []
    checked = 0

    log.info("Enriching repos with metadata …")

    for full_name, info in repo_map.items():
        checked += 1
        log.info("  [%d/%d] Checking %s …", checked, len(repo_map), full_name)

        # Fetch repo details
        time.sleep(1)  # gentle pacing
        details = get_repo_details(full_name)
        if not details:
            continue

        stars = details.get("stargazers_count", 0)
        if stars < MIN_STARS:
            log.info("    ↳ Skipping (only %d stars)", stars)
            continue

        pushed_at_str = details.get("pushed_at", "")
        if pushed_at_str:
            try:
                pushed_at = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
                if pushed_at < cutoff:
                    log.info("    ↳ Skipping (last push %s, before cutoff)", pushed_at.date())
                    continue
            except ValueError:
                pass

        # Fetch README
        time.sleep(0.5)
        readme = get_readme_text(full_name)
        project_name = extract_company_from_readme(readme) or details.get("name", full_name)

        # Detect gap
        gap, play = detect_gap(readme, info["agentic"], info["payment"])

        # Fetch owner / top contributor info
        owner_email = ""
        owner_linkedin = ""
        owner_twitter = ""
        owner_login = details.get("owner", {}).get("login", "")

        time.sleep(0.5)
        user = get_user_details(owner_login)
        if user:
            owner_email = user.get("email", "") or ""
            blog = user.get("blog", "") or ""
            twitter = user.get("twitter_username", "") or ""
            bio = user.get("bio", "") or ""

            if "linkedin.com" in blog:
                owner_linkedin = blog
            elif "linkedin.com" in bio:
                match = re.search(r"https?://[^\s)]*linkedin\.com/in/[^\s)]+", bio)
                if match:
                    owner_linkedin = match.group()

            if twitter:
                owner_twitter = f"https://x.com/{twitter}"

        # If no email from owner, try README or contributors
        if not owner_email:
            readme_emails = extract_emails_from_text(readme)
            if readme_emails:
                owner_email = readme_emails[0]

        if not owner_email:
            time.sleep(0.5)
            contributors = get_contributors(full_name, limit=3)
            for contrib in contributors:
                login = contrib.get("login", "")
                if login:
                    time.sleep(0.3)
                    u = get_user_details(login)
                    if u and u.get("email"):
                        owner_email = u["email"]
                        break

        lead = {
            "Rank": 0,  # assigned later
            "Startup/Project": project_name[:80],
            "Repo URL": details.get("html_url", f"https://github.com/{full_name}"),
            "Stars": stars,
            "Last Updated": pushed_at_str[:10] if pushed_at_str else "",
            "Agentic Tech Found": ", ".join(sorted(info["agentic"])),
            "Payment Tech Found": ", ".join(sorted(info["payment"])),
            "The Gap": gap,
            "Natural's Play": play,
            "Owner GitHub": f"https://github.com/{owner_login}" if owner_login else "",
            "Owner Email": owner_email,
            "Owner LinkedIn/X": owner_linkedin or owner_twitter,
        }
        leads.append(lead)
        log.info("    ✓ Added lead: %s (%d★)", project_name[:40], stars)

        if len(leads) >= MAX_LEADS:
            break

    # Sort by stars descending and assign ranks
    leads.sort(key=lambda x: x["Stars"], reverse=True)
    for i, lead in enumerate(leads, 1):
        lead["Rank"] = i

    return leads


# ─── Step 4: Write CSV ──────────────────────────────────────────────────────

CSV_COLUMNS = [
    "Rank",
    "Startup/Project",
    "Repo URL",
    "Stars",
    "Last Updated",
    "Agentic Tech Found",
    "Payment Tech Found",
    "The Gap",
    "Natural's Play",
    "Owner GitHub",
    "Owner Email",
    "Owner LinkedIn/X",
]


def write_csv(leads: list[dict], filepath: str):
    """Write the leads to a CSV file."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(leads)
    log.info("Wrote %d leads to %s", len(leads), filepath)


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print(r"""
    ╔══════════════════════════════════════════════════════════╗
    ║       Agent-Spend GitHub Intelligence Tool              ║
    ║       Finding the Natural Top 100 Leads                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    if not GITHUB_TOKEN:
        log.error(
            "GITHUB_TOKEN is not set.\n"
            "  Create a token at https://github.com/settings/tokens\n\n"
            "  Option 1 – Environment variable:\n"
            '    PowerShell:  $env:GITHUB_TOKEN = "ghp_your_token_here"\n'
            "    CMD:         set GITHUB_TOKEN=ghp_your_token_here\n"
            "    Linux/Mac:   export GITHUB_TOKEN=ghp_your_token_here\n\n"
            "  Option 2 – Create a .env file in this folder with:\n"
            "    GITHUB_TOKEN=ghp_your_token_here\n"
        )
        sys.exit(1)

    # Step 1 – Search
    log.info("═══ Step 1: Searching GitHub for agentic + payment repos ═══")
    repo_map = search_repos_via_code()

    if not repo_map:
        log.warning("No repos found. Try adjusting the search libraries or reducing MIN_STARS.")
        sys.exit(0)

    # Step 2 & 3 – Enrich & Build leads
    log.info("═══ Step 2: Enriching repos & building lead list ═══")
    leads = build_leads(repo_map)

    if not leads:
        log.warning("No leads passed the filters (stars >= %d, updated in last %d days).", MIN_STARS, DAYS_RECENT)
        sys.exit(0)

    # Step 4 – Write CSV
    log.info("═══ Step 3: Writing CSV output ═══")
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    write_csv(leads, output_path)

    # Summary
    print(f"\n{'─' * 60}")
    print(f"  ✅  Done!  {len(leads)} leads written to: {output_path}")
    print(f"{'─' * 60}")
    print(f"  Top 5 leads:")
    for lead in leads[:5]:
        print(f"    {lead['Rank']}. {lead['Startup/Project']}  ({lead['Stars']}★)")
        print(f"       Tech: {lead['Agentic Tech Found']} + {lead['Payment Tech Found']}")
        print(f"       Gap:  {lead['The Gap']}")
    print(f"{'─' * 60}\n")


if __name__ == "__main__":
    main()
