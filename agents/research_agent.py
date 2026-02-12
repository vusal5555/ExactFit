import json
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from services.llm import invoke_llm
from services.search import google_search_sync, search_news_sync
from services.scrape import extract_company_website
from services.yc import get_yc_companies
from services.porduct_hunt import get_recent_launches
from services.crunchbase import get_recently_funded


class ResearchState(TypedDict):
    icp: str
    search_queries: List[str]
    raw_results: List[Dict[str, Any]]
    parsed_companies: List[Dict[str, Any]]
    errors: List[str]


def generate_queries(state: ResearchState) -> ResearchState:
    """Node 1: Parse ICP and generate targeted search queries."""

    prompt = """You are a B2B sales research expert. Given an Ideal Customer Profile (ICP), 
    generate 10 Google search queries to find companies showing BUYING INTENT signals.

    ICP: {icp}

    Use these job board search patterns (6-7 queries):
    - site:greenhouse.io "job title" - Greenhouse jobs
    - site:lever.co "job title" - Lever jobs
    - site:indeed.com "job title" "company type" - Indeed jobs
    - site:glassdoor.com/job "job title" - Glassdoor jobs
    - site:linkedin.com/jobs "job title" - LinkedIn jobs
    - site:wellfound.com/jobs "job title" - Startup jobs
    - site:builtin.com/jobs "job title" - Tech company jobs

    Use these funding news patterns (3-4 queries) - NO YEAR NEEDED, news search returns recent results:
    - "raised" "series A" "SaaS" site:techcrunch.com
    - "funding" "B2B" "startup" site:crunchbase.com
    - "announces" "million" "round" site:businesswire.com
    - "series A" OR "seed round" "SaaS"

    Return ONLY valid JSON:
    {{
        "queries": [
            "site:greenhouse.io sales development representative SaaS",
            "site:lever.co SDR BDR startup",
            "site:indeed.com SDR SaaS",
            "site:wellfound.com/jobs SDR startup",
            "site:builtin.com/jobs sales development",
            "site:linkedin.com/jobs SDR",
            "raised series A SaaS site:techcrunch.com",
            "B2B startup funding site:crunchbase.com",
            "SaaS series A million site:businesswire.com",
            "seed round B2B startup"
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
            "raised series A SaaS site:techcrunch.com",
        ]
        state["errors"].append("Failed to parse LLM query response")

    return {**state, "search_queries": queries}


def search_web(state: ResearchState) -> ResearchState:
    """Node 2: Execute searches and collect results with real domains."""

    all_results = []

    for query in state["search_queries"][:10]:
        try:
            # Check if this is a funding/news query
            is_news_query = (
                any(
                    site in query.lower()
                    for site in ["techcrunch.com", "crunchbase.com", "businesswire.com"]
                )
                or any(
                    term in query.lower()
                    for term in ["raised", "funding", "series a", "seed round"]
                )
                and "site:greenhouse" not in query.lower()
                and "site:lever" not in query.lower()
            )

            if is_news_query:
                # Use news search for funding queries
                results = search_news_sync(query, num_results=10)
                for r in results:
                    result_data = {
                        "title": r.get("title", ""),
                        "url": r.get("link", ""),
                        "snippet": r.get("snippet", ""),
                        "query": query,
                        "company_slug": None,
                        "source_type": "funding_news",
                        "verified_domain": None,
                        "date": r.get("date", ""),
                    }
                    all_results.append(result_data)
            else:
                # Use regular search for job boards
                results = google_search_sync(query, num_results=10)
                for r in results:
                    result_data = {
                        "title": r.get("title", ""),
                        "url": r.get("link", ""),
                        "snippet": r.get("snippet", ""),
                        "query": query,
                        "company_slug": None,
                        "source_type": None,
                        "verified_domain": None,
                    }

                    url = r.get("link", "")

                    # Greenhouse
                    if "greenhouse.io" in url:
                        parts = url.split("greenhouse.io/")
                        if len(parts) > 1:
                            result_data["company_slug"] = parts[1].split("/")[0]
                            result_data["source_type"] = "greenhouse"
                            real_domain = extract_company_website(url)
                            if real_domain:
                                result_data["verified_domain"] = real_domain

                    # Lever
                    elif "lever.co" in url:
                        parts = url.split("lever.co/")
                        if len(parts) > 1:
                            result_data["company_slug"] = parts[1].split("/")[0]
                            result_data["source_type"] = "lever"
                            real_domain = extract_company_website(url)
                            if real_domain:
                                result_data["verified_domain"] = real_domain

                    # Wellfound
                    elif "wellfound.com" in url:
                        if "/company/" in url:
                            parts = url.split("/company/")
                            if len(parts) > 1:
                                result_data["company_slug"] = parts[1].split("/")[0]
                                result_data["source_type"] = "wellfound"
                                real_domain = extract_company_website(url)
                                if real_domain:
                                    result_data["verified_domain"] = real_domain

                    # Built In
                    elif "builtin.com" in url:
                        result_data["source_type"] = "builtin"
                        real_domain = extract_company_website(url)
                        if real_domain:
                            result_data["verified_domain"] = real_domain

                    # Indeed
                    elif "indeed.com" in url:
                        if "/cmp/" in url:
                            parts = url.split("/cmp/")
                            if len(parts) > 1:
                                result_data["company_slug"] = parts[1].split("/")[0]
                                result_data["source_type"] = "indeed"
                                real_domain = extract_company_website(url)
                                if real_domain:
                                    result_data["verified_domain"] = real_domain

                    # Glassdoor
                    elif "glassdoor.com" in url:
                        result_data["source_type"] = "glassdoor"
                        real_domain = extract_company_website(url)
                        if real_domain:
                            result_data["verified_domain"] = real_domain

                    # LinkedIn
                    elif "linkedin.com" in url:
                        if "/company/" in url:
                            parts = url.split("/company/")
                            if len(parts) > 1:
                                result_data["company_slug"] = parts[1].split("/")[0]
                        result_data["source_type"] = "linkedin"

                    # Funding news sources
                    elif any(
                        site in url
                        for site in [
                            "techcrunch.com",
                            "crunchbase.com",
                            "businesswire.com",
                        ]
                    ):
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

    CRITICAL RULES FOR DOMAINS:
    1. If "verified_domain" exists and is not null, YOU MUST USE IT
    2. If no verified_domain, use "company_slug" + ".com" as a guess
    3. For funding news, extract the company name and guess domain from company name

    For EACH result that represents a real company:

    Extract:
    - company_name: The actual company name
    - domain: Use verified_domain if available, otherwise guess from company name
    - source_url: The URL from the search result
    - signal_type: "hiring" for job posts, "funding" for funding news
    - signal_detail: Specific signal (e.g., "Hiring SDR", "Raised $10M Series A")

    Return ONLY valid JSON:
    {{
        "companies": [
            {{
                "company_name": "Acme Corp",
                "domain": "acme.com",
                "source_url": "https://boards.greenhouse.io/acmecorp/jobs/123",
                "signal_type": "hiring",
                "signal_detail": "Hiring Sales Development Representative"
            }},
            {{
                "company_name": "TechStart",
                "domain": "techstart.io",
                "source_url": "https://techcrunch.com/...",
                "signal_type": "funding",
                "signal_detail": "Raised $5M Series A"
            }}
        ]
    }}

    Skip generic listings. Only include REAL companies with clear signals."""

    results_text = json.dumps(state["raw_results"][:25], indent=2)

    result = invoke_llm(
        system_prompt=prompt.format(results=results_text),
        user_message="Extract companies with hiring and funding signals.",
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

    # Deduplicate by domain
    seen_domains = set()
    unique_companies = []
    for company in companies:
        domain = company.get("domain", "").lower()
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            unique_companies.append(company)

    return {**state, "parsed_companies": unique_companies}


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
        icp: Ideal Customer Profile

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


def research_all_sources(
    icp: str,
    include_yc: bool = True,
    include_ph: bool = True,
    include_funding: bool = True,
) -> Dict[str, Any]:
    """
    Research ICP using ALL sources:
    - Job boards (existing)
    - Y Combinator
    - Product Hunt
    - Funding news
    """

    all_companies = []
    sources_used = []
    errors = []

    # 1. Job boards (existing research agent)
    print("🔍 Searching job boards...")
    try:
        job_results = research_icp(icp)
        all_companies.extend(job_results["companies"])
        sources_used.append("job_boards")
        errors.extend(job_results.get("errors", []))
    except Exception as e:
        errors.append(f"Job board search failed: {e}")

    # 2. Y Combinator
    if include_yc:
        print("🚀 Searching Y Combinator...")
        try:

            yc_companies = get_yc_companies(limit=30)
            all_companies.extend(yc_companies)
            sources_used.append("yc")
            print(f"   Found {len(yc_companies)} YC companies")
        except Exception as e:
            errors.append(f"YC search failed: {e}")

    # 3. Product Hunt
    if include_ph:
        print("🎯 Searching Product Hunt...")
        try:

            ph_companies = get_recent_launches(limit=30)
            all_companies.extend(ph_companies)
            sources_used.append("producthunt")
            print(f"   Found {len(ph_companies)} PH launches")
        except Exception as e:
            errors.append(f"Product Hunt search failed: {e}")

    # 4. Recently funded companies
    if include_funding:
        print("💰 Searching for funded companies...")
        try:

            funded_companies = get_recently_funded(limit=30)
            all_companies.extend(funded_companies)
            sources_used.append("funding")
            print(f"   Found {len(funded_companies)} funded companies")
        except Exception as e:
            errors.append(f"Funding search failed: {e}")

    # Deduplicate by domain
    seen_domains = set()
    unique_companies = []

    for company in all_companies:
        domain = company.get("domain", "").lower()

        if not domain or "." not in domain or len(domain) < 4:
            continue

        if domain not in seen_domains:
            seen_domains.add(domain)

            if "status" not in company:
                company["status"] = "discovered"
            if "score" not in company:
                company["score"] = 0
            if "signals" not in company:
                company["signals"] = {
                    company.get("signal_type", "unknown"): company.get(
                        "signal_detail", ""
                    )
                }

            unique_companies.append(company)

    by_source = {
        "job_boards": len(
            [c for c in unique_companies if c.get("signal_type") == "hiring"]
        ),
        "funding": len(
            [c for c in unique_companies if c.get("signal_type") == "funding"]
        ),
        "yc": len(
            [c for c in unique_companies if c.get("signal_type") == "yc_company"]
        ),
        "producthunt": len(
            [c for c in unique_companies if c.get("signal_type") == "product_launch"]
        ),
    }

    print(f"\n📊 Total unique companies: {len(unique_companies)}")

    return {
        "icp": icp,
        "companies": unique_companies,
        "total_found": len(unique_companies),
        "sources_used": sources_used,
        "by_source": by_source,
        "errors": errors,
    }


if __name__ == "__main__":
    print("🔍 ExactFit Research Agent")
    print("=" * 50)

    icp = "SaaS companies hiring SDRs"
    print(f"\nSearching for: {icp}\n")

    result = research_icp(icp)

    print(f"Queries used:")
    for q in result["queries_used"]:
        print(f"  • {q}")

    print(f"\nFound {result['total_found']} companies:\n")

    hiring = [c for c in result["companies"] if c["signal_type"] == "hiring"]
    funding = [c for c in result["companies"] if c["signal_type"] == "funding"]

    print(f"📊 Hiring signals: {len(hiring)}")
    print(f"📊 Funding signals: {len(funding)}\n")

    for company in result["companies"][:10]:
        emoji = "💼" if company["signal_type"] == "hiring" else "💰"
        print(f"  {emoji} {company['company_name']}")
        print(f"     Domain: {company['domain']}")
        print(f"     Signal: {company['signal_detail']}")
        print()

    if result["errors"]:
        print(f"⚠️ Errors: {result['errors']}")
