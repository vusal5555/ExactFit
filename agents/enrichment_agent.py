import json
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from services.hunter import find_email, verify_email, domain_search
from services.pdl import find_person, enrich_email


class EnrichmentState(TypedDict):
    leads: List[Dict[str, Any]]
    enriched_leads: List[Dict[str, Any]]
    failed_leads: List[Dict[str, Any]]
    errors: List[str]
    target_job_title: str  # NEW: Customer's target role


def hunter_enrich(state: EnrichmentState) -> EnrichmentState:
    """Node 1: Find emails using Hunter.io"""

    hunter_results = []
    target_title = state.get("target_job_title", None)

    for lead in state["leads"]:
        domain = lead.get("domain", "")

        if not domain:
            state["failed_leads"].append({**lead, "error": "No domain available"})
            continue

        # Use customer's target job title (dynamic, not hardcoded)
        result = find_email(domain, job_title=target_title)

        if result.get("email"):
            hunter_results.append(
                {
                    **lead,
                    "hunter_email": result["email"],
                    "hunter_name": f"{result.get('first_name', '')} {result.get('last_name', '')}".strip(),
                    "hunter_title": result.get("position", ""),
                    "hunter_confidence": result.get("confidence", 0),
                    "hunter_verified": result.get("verified", False),
                }
            )
            continue

        # Fallback: domain_search (find anyone at company)
        search_result = domain_search(domain, limit=5)

        if search_result.get("emails"):
            # If we have a target title, try to match it
            best = None

            if target_title:
                best = find_title_match(search_result["emails"], target_title)

            # If no match or no target title, take first result
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


def find_title_match(contacts: List[Dict], target_title: str) -> Optional[Dict]:
    """Find contact whose title best matches target."""

    if not target_title:
        return None

    target_lower = target_title.lower()
    target_words = set(target_lower.replace("-", " ").split())

    stop_words = {"of", "the", "and", "a", "an", "at", "in", "for"}
    target_words = target_words - stop_words

    best_match = None
    best_score = 0

    for contact in contacts:
        # Handle None values
        position = contact.get("position") or ""
        position = position.lower()
        position_words = set(position.replace("-", " ").split()) - stop_words

        if not position_words:
            continue

        # Exact match
        if target_lower in position or position in target_lower:
            return contact

        # Word overlap
        matching = target_words & position_words
        score = len(matching) / max(len(target_words), 1)

        if score > best_score:
            best_score = score
            best_match = contact

    # Return if reasonable match (>40%)
    if best_score >= 0.4:
        return best_match

    return None


def pdl_enrich(state: EnrichmentState) -> EnrichmentState:
    """Node 2: Cross-validate with PDL and calculate confidence."""

    final_leads = []
    target_title = state.get("target_job_title", None)

    for lead in state["enriched_leads"]:
        hunter_email = lead.get("hunter_email")
        domain = lead.get("domain", "")

        if not hunter_email:
            # No Hunter email, try PDL directly
            pdl_result = find_person(domain, job_title=target_title)

            if pdl_result.get("email"):
                lead["contact_email"] = pdl_result["email"]
                lead["contact_name"] = (
                    f"{pdl_result.get('first_name', '')} {pdl_result.get('last_name', '')}".strip()
                )
                lead["contact_title"] = pdl_result.get("title", "")
                lead["confidence"] = 0.6  # Single source
                lead["sources"] = ["pdl"]
                lead["linkedin_url"] = pdl_result.get("linkedin_url", "")
                final_leads.append(lead)
            else:
                state["failed_leads"].append({**lead, "error": "PDL: No email found"})
            continue

        # We have Hunter email, verify with PDL
        pdl_result = enrich_email(hunter_email)

        if pdl_result.get("valid"):
            # PDL confirms Hunter's email
            lead["contact_email"] = hunter_email
            lead["contact_name"] = (
                lead.get("hunter_name")
                or f"{pdl_result.get('first_name', '')} {pdl_result.get('last_name', '')}".strip()
            )
            lead["contact_title"] = lead.get("hunter_title") or pdl_result.get(
                "title", ""
            )
            lead["confidence"] = 0.9  # Two sources agree
            lead["sources"] = ["hunter", "pdl"]
            lead["linkedin_url"] = pdl_result.get("linkedin_url", "")
            final_leads.append(lead)
        else:
            # PDL doesn't confirm, try finding someone else
            pdl_person = find_person(domain, job_title=target_title)

            if pdl_person.get("email") and pdl_person["email"] == hunter_email:
                # Same email found independently
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.85
                lead["sources"] = ["hunter", "pdl"]
                final_leads.append(lead)
            elif pdl_person.get("email"):
                # PDL found different person
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.7
                lead["sources"] = ["hunter"]
                lead["pdl_alternative"] = pdl_person["email"]
                final_leads.append(lead)
            else:
                # Only Hunter found something
                lead["contact_email"] = hunter_email
                lead["contact_name"] = lead.get("hunter_name", "")
                lead["contact_title"] = lead.get("hunter_title", "")
                lead["confidence"] = 0.6
                lead["sources"] = ["hunter"]
                final_leads.append(lead)

    return {**state, "enriched_leads": final_leads}


def build_enrichment_agent():
    """Build the LangGraph workflow."""

    workflow = StateGraph(EnrichmentState)

    workflow.add_node("hunter_enrich", hunter_enrich)
    workflow.add_node("pdl_enrich", pdl_enrich)

    workflow.set_entry_point("hunter_enrich")

    workflow.add_edge("hunter_enrich", "pdl_enrich")
    workflow.add_edge("pdl_enrich", END)

    return workflow.compile()


def enrich_leads(
    leads: List[Dict[str, Any]], target_job_title: str = None
) -> Dict[str, Any]:
    """
    Main function: Enrich leads with contact emails.

    Args:
        leads: List of leads from Research Agent
        target_job_title: Customer's target role (e.g., "Head of Support", "VP Sales")

    Returns:
        Dict with enriched leads, failed leads, and stats
    """
    agent = build_enrichment_agent()

    result = agent.invoke(
        {
            "leads": leads,
            "enriched_leads": [],
            "failed_leads": [],
            "errors": [],
            "target_job_title": target_job_title or "",
        }
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
            "company_name": "Zendesk",
            "domain": "zendesk.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring Support Manager",
        },
    ]

    # Test with different job titles
    print("\n--- Test 1: Finding VP Sales ---")
    result1 = enrich_leads(test_leads, target_job_title="VP Sales")
    print(f"Found {result1['stats']['enriched']} contacts")

    print("\n--- Test 2: Finding Head of Support ---")
    result2 = enrich_leads(test_leads, target_job_title="Head of Support")
    print(f"Found {result2['stats']['enriched']} contacts")

    print("\n--- Test 3: Finding HR Manager ---")
    result3 = enrich_leads(test_leads, target_job_title="HR Manager")
    print(f"Found {result3['stats']['enriched']} contacts")

    print("\nEnriched Leads (VP Sales):")
    for lead in result1["enriched_leads"]:
        print(f"\n  🏢 {lead['company_name']}")
        print(f"     Email: {lead.get('contact_email', 'N/A')}")
        print(f"     Name: {lead.get('contact_name', 'N/A')}")
        print(f"     Title: {lead.get('contact_title', 'N/A')}")
        print(f"     Confidence: {lead.get('confidence', 0) * 100:.0f}%")
