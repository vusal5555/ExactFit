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
    generate 5 Google search queries to find companies showing BUYING INTENT signals.

    ICP: {icp}

    Focus on these HIGH-INTENT signals:
    1. Companies actively hiring sales roles (SDR, BDR, AE, Sales Manager)
    2. Companies that recently raised funding
    3. Companies using competitor tools (Apollo, ZoomInfo, Lusha)

    Use these search patterns:
    - site:greenhouse.io "job title" - for Greenhouse job boards
    - site:lever.co "job title" - for Lever job boards  
    - site:linkedin.com/jobs "job title" "company type" - for LinkedIn jobs
    - "company raised" "$XM" "series A" site:techcrunch.com - for funding news

    Return ONLY valid JSON:
    {{
        "queries": [
            "site:greenhouse.io sales development representative SaaS",
            "site:lever.co SDR BDR startup 2024",
            "site:linkedin.com/jobs SDR series A startup",
            "raised series A 2024 SaaS B2B site:techcrunch.com",
            "site:lever.co account executive B2B"
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
        ]
        state["errors"].append("Failed to parse LLM query response")

    return {**state, "search_queries": queries}


def search_web(state: ResearchState) -> ResearchState:
    """Node 2: Execute searches and collect results."""

    all_results = []

    for query in state["search_queries"]:
        try:
            results = google_search_sync(query, num_results=5)
            for r in results:
                all_results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("link", ""),
                        "snippet": r.get("snippet", ""),
                        "query": query,
                    }
                )
        except Exception as e:
            state["errors"].append(f"Search failed for '{query}': {str(e)}")

    seen_url = set()
    unique_results = []

    for r in all_results:
        if r["url"] not in seen_url:
            seen_url.add(r["url"])
            unique_results.append(r)
    return {**state, "raw_results": unique_results}


def parse_companies(state: ResearchState) -> ResearchState:
    """Node 3: Extract company data from search results using LLM."""

    if not state["raw_results"]:
        return {**state, "parsed_companies": []}

    prompt = """You are extracting company information from search results.

    Search Results:
    {results}

    For EACH result that represents a real company (skip aggregator sites, job board homepages):

    Extract:
    - company_name: The actual company name (not "Greenhouse" or "Lever")
    - domain: Their website domain (guess from company name if needed)
    - source_url: The URL from the search result
    - signal_type: "hiring", "funding", or "tech_stack"
    - signal_detail: What specific signal was found (e.g., "Hiring SDR", "Raised $5M Series A")

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

    Skip results that are:
    - Job board homepages (greenhouse.io/explore, lever.co/jobs)
    - News article listings (techcrunch.com/tag/...)
    - Generic company directories

    Only include REAL companies with REAL signals."""

    results_text = json.dumps(state["raw_results"][:20], indent=2)

    result = invoke_llm(
        system_prompt=prompt.format(results=results_text),
        user_message="Extract companies from these search results.",
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
