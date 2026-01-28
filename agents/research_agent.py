import json
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from services.llm import invoke_llm
from services.search import google_search_sync
from services.scrape import scrape_page


class ResearchState(TypedDict):
    icp: str
    search_queries: List[str]
    raw_results: List[Dict[str, Any]]
    parsed_companies: List[Dict[str, Any]]
    errors: List[str]


def generate_queries(state: ResearchState) -> ResearchState:
    """Node 1: Parse ICP and generate targeted search queries."""

    prompt = """You are a B2B sales research expert. Given an Ideal Customer Profile (ICP), 
    generate 8 Google search queries to find companies showing BUYING INTENT signals.

    ICP: {icp}

    Use these job board search patterns:
    - site:greenhouse.io "job title" - Greenhouse jobs
    - site:lever.co "job title" - Lever jobs
    - site:indeed.com "job title" "company type" - Indeed jobs
    - site:glassdoor.com/job "job title" - Glassdoor jobs
    - site:linkedin.com/jobs "job title" - LinkedIn jobs
    - site:wellfound.com/jobs "job title" - Startup jobs (AngelList)
    - site:builtin.com/jobs "job title" - Tech company jobs

    Also search for funding signals:
    - "raised" "$XM" "series A" site:techcrunch.com
    - "announces funding" site:crunchbase.com

    Return ONLY valid JSON:
    {{
        "queries": [
            "site:greenhouse.io sales development representative",
            "site:lever.co SDR BDR",
            "site:indeed.com SDR SaaS startup",
            "site:glassdoor.com/job sales development representative",
            "site:linkedin.com/jobs SDR series A",
            "site:wellfound.com/jobs SDR startup",
            "site:builtin.com/jobs sales development",
            "raised series A 2024 SaaS site:techcrunch.com"
        ]
    }}"""

    result = invoke_llm(
        system_prompt=prompt.format(icp=state["icp"]),
        user_message=f"Generate search queries for this ICP: {state['icp']}",
    )

    try:
        clean_result = result.strip()
        if clean_result.startswith("```"):
            clean_result = clean_result.split("```")[1]
            if clean_result.startswith("json"):
                clean_result = clean_result[4:]

        parsed = json.loads(clean_result)
        queries = parsed.get("queries", [])
    except json.JSONDecodeError:
        queries = [
            f"site:greenhouse.io SDR {state['icp']}",
            f"site:lever.co BDR {state['icp']}",
            f"site:indeed.com SDR {state['icp']}",
        ]
        state["errors"].append("Failed to parse LLM query response")

    return {**state, "search_queries": queries}


def search_web(state: ResearchState) -> ResearchState:
    """Node 2: Execute searches and collect results with real domains."""

    all_results = []

    for query in state["search_queries"][:8]:  # Increased to 8 queries
        try:
            results = google_search_sync(query, num_results=10)
            for r in results:
                result_data = {
                    "title": r.get("title", ""),
                    "url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                    "query": query,
                    "company_slug": None,
                    "source_type": None,
                }

                url = r.get("link", "")

                # Greenhouse: boards.greenhouse.io/companyname/...
                if "greenhouse.io" in url:
                    parts = url.split("greenhouse.io/")
                    if len(parts) > 1:
                        result_data["company_slug"] = parts[1].split("/")[0]
                        result_data["source_type"] = "greenhouse"

                # Lever: jobs.lever.co/companyname/...
                elif "lever.co" in url:
                    parts = url.split("lever.co/")
                    if len(parts) > 1:
                        result_data["company_slug"] = parts[1].split("/")[0]
                        result_data["source_type"] = "lever"

                # Wellfound: wellfound.com/company/companyname/...
                elif "wellfound.com" in url:
                    if "/company/" in url:
                        parts = url.split("/company/")
                        if len(parts) > 1:
                            result_data["company_slug"] = parts[1].split("/")[0]
                            result_data["source_type"] = "wellfound"

                # Built In: builtin.com/company/companyname or builtin.com/job/...
                elif "builtin.com" in url:
                    result_data["source_type"] = "builtin"

                # Indeed: indeed.com/cmp/companyname/...
                elif "indeed.com" in url:
                    if "/cmp/" in url:
                        parts = url.split("/cmp/")
                        if len(parts) > 1:
                            result_data["company_slug"] = parts[1].split("/")[0]
                            result_data["source_type"] = "indeed"

                # Glassdoor: glassdoor.com/job-listing/... or /Overview/...EI_IE12345
                elif "glassdoor.com" in url:
                    result_data["source_type"] = "glassdoor"

                # LinkedIn: linkedin.com/jobs/view/... or /company/...
                elif "linkedin.com" in url:
                    if "/company/" in url:
                        parts = url.split("/company/")
                        if len(parts) > 1:
                            result_data["company_slug"] = parts[1].split("/")[0]
                    result_data["source_type"] = "linkedin"

                # TechCrunch/Crunchbase: funding news
                elif "techcrunch.com" in url or "crunchbase.com" in url:
                    result_data["source_type"] = "funding_news"

                all_results.append(result_data)

        except Exception as e:
            state["errors"].append(f"Search failed for '{query}': {str(e)}")

    # Deduplicate by URL
    seen_urls = set()
    unique_results = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)

    return {**state, "raw_results": unique_results}


def parse_companies(state: ResearchState) -> ResearchState:
    """Node 3: Extract company data from search results using LLM."""

    if not state["raw_results"]:
        return {**state, "parsed_companies": []}

    prompt = """You are extracting company information from search results.

    Search Results:
    {results}

    IMPORTANT RULES FOR DOMAINS:
    1. If "company_slug" is provided, use it to find the real domain
    2. Search the snippet for actual website URLs (look for "website:", ".com", ".io", etc.)
    3. If company_slug is "acmecorp", the domain is likely "acmecorp.com" or "acmecorp.io"
    4. DO NOT guess random domains. If unsure, use company_slug + ".com"

    For EACH result that represents a real company:

    Extract:
    - company_name: The actual company name (not "Greenhouse" or "Lever")
    - domain: Their REAL website domain (use company_slug as base)
    - source_url: The URL from the search result
    - signal_type: "hiring", "funding", or "tech_stack"
    - signal_detail: What specific signal was found

    Return ONLY valid JSON:
    {{
        "companies": [
            {{
                "company_name": "Acme Corp",
                "domain": "acmecorp.com",
                "source_url": "https://boards.greenhouse.io/acmecorp/jobs/123",
                "signal_type": "hiring",
                "signal_detail": "Hiring Sales Development Representative"
            }}
        ]
    }}

    Skip job board homepages and news listings. Only include REAL companies."""

    results_text = json.dumps(state["raw_results"][:20], indent=2)

    result = invoke_llm(
        system_prompt=prompt.format(results=results_text),
        user_message="Extract companies from these search results. Pay attention to company_slug for domains.",
    )

    try:
        clean_result = result.strip()
        if clean_result.startswith("```"):
            clean_result = clean_result.split("```")[1]
            if clean_result.startswith("json"):
                clean_result = clean_result[4:]

        parsed = json.loads(clean_result)
        companies = parsed.get("companies", [])
    except json.JSONDecodeError:
        companies = []
        state["errors"].append("Failed to parse company extraction response")

    # Add status for pipeline
    for company in companies:
        company["status"] = "discovered"
        company["score"] = 0
        company["signals"] = {company["signal_type"]: company["signal_detail"]}

    return {**state, "parsed_companies": companies}


def build_research_agent():
    """Build the LangGraph workflow."""

    workflow = StateGraph(ResearchState)

    workflow.add_node("generate_queries", generate_queries)
    workflow.add_node("search_web", search_web)
    workflow.add_node("parse_companies", parse_companies)

    workflow.set_entry_point("generate_queries")

    workflow.add_edge("generate_queries", "search_web")
    workflow.add_edge("search_web", "parse_companies")
    workflow.add_edge("parse_companies", END)

    return workflow.compile()


def research_icp(icp: str) -> Dict[str, Any]:
    """
    Main function: Research an ICP and return companies with buying signals.

    Args:
        icp: Ideal Customer Profile (e.g., "SaaS companies 10-50 employees hiring SDRs")

    Returns:
        Dict with companies list and metadata
    """
    agent = build_research_agent()

    result = agent.invoke(
        {
            "icp": icp,
            "search_queries": [],
            "raw_results": [],
            "parsed_companies": [],
            "errors": [],
        }
    )

    return {
        "icp": icp,
        "companies": result["parsed_companies"],
        "total_found": len(result["parsed_companies"]),
        "queries_used": result["search_queries"],
        "errors": result["errors"],
    }


if __name__ == "__main__":
    print("🔍 ExactFit Research Agent")
    print("=" * 50)

    icp = "SaaS companies 10-50 employees hiring SDRs"
    print(f"\nSearching for: {icp}\n")

    result = research_icp(icp)

    print(f"Queries used:")
    for q in result["queries_used"]:
        print(f"  • {q}")

    print(f"\nFound {result['total_found']} companies:\n")

    for company in result["companies"][:10]:
        print(f"  🏢 {company['company_name']}")
        print(f"     Domain: {company['domain']}")
        print(f"     Signal: {company['signal_type']} - {company['signal_detail']}")
        print(f"     Source: {company['source_url'][:60]}...")
        print()

    if result["errors"]:
        print(f"⚠️ Errors: {result['errors']}")
