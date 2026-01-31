import json
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from services.hunter import find_email, verify_email, domain_search
from services.pdl import find_person, enrich_email


class EnrichmentState(TypedDict):
    leads: List[Dict[str, Any]]  # Input: leads from Research Agent
    enriched_leads: List[Dict[str, Any]]  # Output: leads with emails
    failed_leads: List[Dict[str, Any]]  # Leads we couldn't enrich
    errors: List[str]


def hunter_enrich(state: EnrichmentState) -> EnrichmentState:
    """Node 1: Find emails using Hunter.io"""

    hunter_results = []

    for lead in state["leads"]:
        domain = lead.get("domain", "")

        if not domain:
            state["failed_leads"].append({**lead, "error": "No domain available"})
            continue

        result = find_email(domain, role="sales")

        if result.get("email"):
            hunter_results.append(
                {
                    **lead,
                    "hunter_name": f"{result.get('first_name', '')} {result.get('last_name', '')}".strip(),
                    "hunter_title": result.get("position", ""),
                    "hunter_confidence": result.get("confidence", 0),
                    "hunter_verified": result.get("verified", False),
                }
            )
            continue

        search_result = domain_search(domain, limit=3)

        if search_result.get("emails"):

            best = None

            for person in search_result["emails"]:
                if not person:
                    continue
                dept = (person.get("department") or "").lower()
                seniority = (person.get("seniority") or "").lower()

                if "sales" in dept or seniority in ["executive", "senior", "manager"]:
                    best = person
                    break

            if not best:
                best = search_result["emails"][0]

            hunter_results.append(
                {
                    **lead,
                    "hunter_email": best["email"],
                    "hunter_name": f"{best.get('first_name', '')} {best.get('last_name', '')}".strip(),
                    "hunter_title": best.get("position", ""),
                    "hunter_confidence": best.get("confidence", 0),
                    "hunter_verified": False,
                    "company_name_verified": search_result.get(
                        "company", lead.get("company_name", "")
                    ),
                }
            )
            continue

        # Both failed
        state["failed_leads"].append({**lead, "error": "Hunter: No email found"})

    return {**state, "enriched_leads": hunter_results}


def pdl_enrich(state: EnrichmentState) -> EnrichmentState:
    """Node 2: Cross-validate with PDL and calculate confidence."""

    final_leads = []

    for lead in state["enriched_leads"]:
        hunter_email = lead.get("hunter_email")
        domain = lead.get("domain", "")

        if not hunter_email:
            pdl_result = find_person(domain, role="sales")

            if pdl_result.get("email"):
                lead["contact_email"] = pdl_result["email"]
                lead["contact_name"] = (
                    f"{pdl_result.get('first_name', '')} {pdl_result.get('last_name', '')}".strip()
                )
                lead["contact_title"] = pdl_result.get("title", "")
                lead["confidence"] = 0.6  # Base confidence for PDL found email
                lead["sources"] = ["pdl"]
                lead["linkedin_url"] = pdl_result.get("linkedin_url", "")
                final_leads.append(lead)
            else:
                state["failed_leads"].append({**lead, "error": "PDL: No email found"})
            continue

        pdl_result = enrich_email(hunter_email)

        if pdl_result.get("valid"):
            lead["contact_email"] = hunter_email
            lead["contact_name"] = (
                lead.get("hunter_name")
                or f"{pdl_result.get('first_name', '')} {pdl_result.get('last_name', '')}".strip()
            )
            lead["contact_title"] = lead.get("hunter_title") or pdl_result.get(
                "title", ""
            )
            lead["confidence"] = 0.9  # Two sources agree = high confidence
            lead["sources"] = ["hunter", "pdl"]
            lead["linkedin_url"] = pdl_result.get("linkedin_url", "")
            final_leads.append(lead)
        else:
            pdl_person = find_person(domain, role="sales")

            if pdl_person.get("email") and pdl_person["email"] == hunter_email:
                # Same email found independently = high confidence
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.85
                lead["sources"] = ["hunter", "pdl"]
                final_leads.append(lead)
            elif pdl_person.get("email"):
                # PDL found different person - use Hunter but lower confidence
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.7  # Slight disagreement
                lead["sources"] = ["hunter"]
                lead["pdl_alternative"] = pdl_person["email"]
                final_leads.append(lead)
            else:
                # Only Hunter found something
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.6  # Single source
                lead["sources"] = ["hunter"]
                final_leads.append(lead)

    return {**state, "enriched_leads": final_leads}


def build_enrichment_agent():

    workflow = StateGraph(EnrichmentState)

    workflow.add_node("hunter_enrich", hunter_enrich)
    workflow.add_node("pdl_enrich", pdl_enrich)

    workflow.set_entry_point("hunter_enrich")
    workflow.add_edge("hunter_enrich", "pdl_enrich")
    workflow.add_edge("pdl_enrich", END)

    return workflow.compile()


def enrich_leads(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Main function: Enrich leads with contact emails.

    Args:
        leads: List of leads from Research Agent

    Returns:
        Dict with enriched leads, failed leads, and stats
    """
    agent = build_enrichment_agent()

    result = agent.invoke(
        {"leads": leads, "enriched_leads": [], "failed_leads": [], "errors": []}
    )

    # Calculate stats
    total = len(leads)
    enriched = len(result["enriched_leads"])
    failed = len(result["failed_leads"])

    high_confidence = [
        l for l in result["enriched_leads"] if l.get("confidence", 0) >= 0.8
    ]

    return {
        "enriched_leads": result["enriched_leads"],
        "failed_leads": result["failed_leads"],
        "errors": result["errors"],
        "stats": {
            "total_input": total,
            "enriched": enriched,
            "failed": failed,
            "success_rate": round(enriched / total * 100, 1) if total > 0 else 0,
            "high_confidence_count": len(high_confidence),
        },
    }


if __name__ == "__main__":
    print("📧 ExactFit Enrichment Agent")
    print("=" * 50)

    # Test with sample leads
    test_leads = [
        {
            "company_name": "HubSpot",
            "domain": "hubspot.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring SDR",
        },
        {
            "company_name": "Salesforce",
            "domain": "salesforce.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring BDR",
        },
    ]

    print(f"\nEnriching {len(test_leads)} leads...\n")

    result = enrich_leads(test_leads)

    print(f"Stats:")
    print(f"  • Total: {result['stats']['total_input']}")
    print(f"  • Enriched: {result['stats']['enriched']}")
    print(f"  • Failed: {result['stats']['failed']}")
    print(f"  • Success Rate: {result['stats']['success_rate']}%")
    print(f"  • High Confidence: {result['stats']['high_confidence_count']}")

    print(f"\nEnriched Leads:")
    for lead in result["enriched_leads"]:
        print(f"\n  🏢 {lead['company_name']}")
        print(f"     Email: {lead.get('contact_email', 'N/A')}")
        print(f"     Name: {lead.get('contact_name', 'N/A')}")
        print(f"     Title: {lead.get('contact_title', 'N/A')}")
        print(f"     Confidence: {lead.get('confidence', 0) * 100:.0f}%")
        print(f"     Sources: {', '.join(lead.get('sources', []))}")

    if result["failed_leads"]:
        print(f"\nFailed Leads:")
        for lead in result["failed_leads"]:
            print(f"  ✗ {lead['company_name']}: {lead.get('error', 'Unknown error')}")
