from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from services.builtwith import get_tech_stack
from services.reddit import find_competitor_mentions


class ScoringState(TypedDict):
    leads: List[Dict[str, Any]]
    scored_leads: List[Dict[str, Any]]
    customer_config: Dict[str, Any]
    errors: List[str]


# Signal weights (from feedback)
SIGNAL_WEIGHTS = {
    "hiring_sales": 40,  # Hiring SDRs, BDRs, sales roles
    "hiring_multiple": 10,  # Bonus: 3+ sales roles
    "hiring_leadership": 35,  # New VP Sales, Head of Sales
    "funding": 40,  # Recent funding
    "tech_competitor": 15,  # Uses competitor tool
    "tech_target": 10,  # Uses target tool (good fit)
    "reddit_mention": 30,  # Mentioned competitor negatively on Reddit
    "reddit_buying_intent": 35,  # Asking for recommendations
    "g2_complaint": 40,  # Left negative G2 review (hottest)
    "growth_signal": 25,  # Company growing
    "combo_bonus": 10,  # 3+ signals bonus
}


def enrich_with_tech(state: ScoringState) -> ScoringState:
    """Node 1: Check tech stack for each lead."""

    config = state.get("customer_config", {})
    competitors = config.get("competitors", [])
    target_tools = config.get("target_tools", [])
    all_tools = competitors + target_tools

    enriched = []

    for lead in state["leads"]:
        domain = lead.get("domain", "")

        if not domain:
            lead["tech_signals"] = []
            enriched.append(lead)
            continue

        # Check tech stack
        if all_tools:
            tech_result = get_tech_stack(domain, tools_to_detect=all_tools)
        else:
            tech_result = {"detected_tools": [], "error": None}

        detected = tech_result.get("detected_tools", [])

        # Categorize detected tools
        tech_signals = []
        for tool in detected:
            if tool in competitors:
                tech_signals.append(
                    {
                        "type": "tech_competitor",
                        "tool": tool,
                        "detail": f"Uses {tool} (your competitor)",
                    }
                )
            elif tool in target_tools:
                tech_signals.append(
                    {
                        "type": "tech_target",
                        "tool": tool,
                        "detail": f"Uses {tool} (good fit)",
                    }
                )

        lead["tech_signals"] = tech_signals
        lead["detected_tools"] = detected
        enriched.append(lead)

    return {**state, "leads": enriched}


def enrich_with_reddit(state: ScoringState) -> ScoringState:
    """Node 2: Check Reddit for mentions of competitors."""

    config = state.get("customer_config", {})
    competitors = config.get("competitors", [])

    if not competitors:
        return state

    # Get Reddit mentions for all competitors
    reddit_signals = {}
    for competitor in competitors:
        mentions = find_competitor_mentions(competitor, limit=10)
        for mention in mentions:
            # Key by URL to avoid duplicates
            reddit_signals[mention["url"]] = mention

    # For now, attach Reddit signals to state (not individual leads)
    # These are general market signals, not company-specific
    state["reddit_signals"] = list(reddit_signals.values())

    return state


def calculate_scores(state: ScoringState) -> ScoringState:
    """Node 3: Calculate score for each lead."""

    config = state.get("customer_config", {})
    competitors = config.get("competitors", [])

    scored = []

    for lead in state["leads"]:
        score = 0
        signals = []

        # --- Hiring Signals ---
        signal_type = lead.get("signal_type", "")
        signal_detail = lead.get("signal_detail", "").lower()

        if signal_type == "hiring":
            # Check for sales roles
            sales_keywords = [
                "sdr",
                "bdr",
                "sales",
                "account executive",
                "ae",
                "business development",
            ]
            if any(kw in signal_detail for kw in sales_keywords):
                score += SIGNAL_WEIGHTS["hiring_sales"]
                signals.append(
                    {
                        "type": "hiring_sales",
                        "points": SIGNAL_WEIGHTS["hiring_sales"],
                        "detail": lead.get("signal_detail", "Hiring sales role"),
                    }
                )

            # Check for leadership roles
            leadership_keywords = ["vp", "head of", "director", "chief", "cro"]
            if any(kw in signal_detail for kw in leadership_keywords):
                score += SIGNAL_WEIGHTS["hiring_leadership"]
                signals.append(
                    {
                        "type": "hiring_leadership",
                        "points": SIGNAL_WEIGHTS["hiring_leadership"],
                        "detail": "Hiring sales leadership",
                    }
                )

        # --- Funding Signals ---
        if (
            signal_type == "funding"
            or "funding" in signal_detail
            or "raised" in signal_detail
        ):
            score += SIGNAL_WEIGHTS["funding"]
            signals.append(
                {
                    "type": "funding",
                    "points": SIGNAL_WEIGHTS["funding"],
                    "detail": lead.get("signal_detail", "Recent funding"),
                }
            )

        # --- Tech Stack Signals ---
        for tech_signal in lead.get("tech_signals", []):
            if tech_signal["type"] == "tech_competitor":
                score += SIGNAL_WEIGHTS["tech_competitor"]
                signals.append(
                    {
                        "type": "tech_competitor",
                        "points": SIGNAL_WEIGHTS["tech_competitor"],
                        "detail": tech_signal["detail"],
                    }
                )
            elif tech_signal["type"] == "tech_target":
                score += SIGNAL_WEIGHTS["tech_target"]
                signals.append(
                    {
                        "type": "tech_target",
                        "points": SIGNAL_WEIGHTS["tech_target"],
                        "detail": tech_signal["detail"],
                    }
                )

        # --- Combo Bonus ---
        if len(signals) >= 3:
            score += SIGNAL_WEIGHTS["combo_bonus"]
            signals.append(
                {
                    "type": "combo_bonus",
                    "points": SIGNAL_WEIGHTS["combo_bonus"],
                    "detail": f"Multiple signals detected ({len(signals)})",
                }
            )

        # Cap score at 100
        score = min(score, 100)

        # Determine tier
        if score >= 80:
            tier = "hot"
            tier_label = "🔥 HOT"
            action = "Contact immediately"
        elif score >= 50:
            tier = "warm"
            tier_label = "🟡 WARM"
            action = "Contact this week"
        else:
            tier = "cold"
            tier_label = "❄️ COLD"
            action = "Keep monitoring"

        lead["score"] = score
        lead["signals"] = signals
        lead["signal_count"] = len(signals)
        lead["tier"] = tier
        lead["tier_label"] = tier_label
        lead["recommended_action"] = action

        scored.append(lead)

    # Sort by score (highest first)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {**state, "scored_leads": scored}


def filter_qualified(state: ScoringState) -> ScoringState:
    """Node 4: Filter leads with minimum signals (3+)."""

    config = state.get("customer_config", {})
    min_signals = config.get("min_signals", 1)  # Default 1 for MVP, increase later
    min_score = config.get("min_score", 0)

    qualified = []
    unqualified = []

    for lead in state["scored_leads"]:
        signal_count = lead.get("signal_count", 0)
        score = lead.get("score", 0)

        if signal_count >= min_signals and score >= min_score:
            qualified.append(lead)
        else:
            unqualified.append(lead)

    state["scored_leads"] = qualified
    state["unqualified_leads"] = unqualified

    return state


def generate_talking_points(state: ScoringState) -> ScoringState:
    """Node 5: Generate personalized talking points for each lead."""

    for lead in state["scored_leads"]:
        talking_points = []

        for signal in lead.get("signals", []):
            signal_type = signal.get("type", "")
            detail = signal.get("detail", "")

            if signal_type == "hiring_sales":
                talking_points.append(f'Reference their sales hiring: "{detail}"')
            elif signal_type == "hiring_leadership":
                talking_points.append(
                    "Mention you can help their new sales leader ramp up faster"
                )
            elif signal_type == "funding":
                talking_points.append(
                    "Congratulate on funding, mention scaling challenges"
                )
            elif signal_type == "tech_competitor":
                tool = detail.replace("Uses ", "").replace(" (your competitor)", "")
                talking_points.append(
                    f"They use {tool} - mention your competitive advantages"
                )
            elif signal_type == "tech_target":
                talking_points.append(f"Good tech fit: {detail}")

        lead["talking_points"] = talking_points

        # Generate sample opener
        if talking_points:
            lead["sample_opener"] = generate_opener(lead)

    return state


def generate_opener(lead: Dict) -> str:
    """Generate a sample email opener based on signals."""

    company = lead.get("company_name", "your company")
    signals = lead.get("signals", [])

    if not signals:
        return ""

    # Pick the strongest signal for opener
    top_signal = signals[0]
    signal_type = top_signal.get("type", "")
    detail = top_signal.get("detail", "")

    if signal_type == "hiring_sales":
        return f"Saw {company} is {detail.lower()} - congrats on the growth! When teams scale outbound, they usually hit data quality issues fast..."
    elif signal_type == "hiring_leadership":
        return f"Noticed {company} is bringing on new sales leadership. New leaders usually want quick wins - happy to show how we help teams book 5+ meetings/week..."
    elif signal_type == "funding":
        return f"Congrats on the funding! As you scale the sales team, data quality becomes critical. We help teams maintain <10% bounce rates..."
    elif signal_type == "tech_competitor":
        tool = detail.replace("Uses ", "").replace(" (your competitor)", "")
        return f"Noticed {company} uses {tool}. Many teams switch to us for better data quality and lower cost. Worth a quick comparison?"

    return ""


def build_scoring_agent():
    """Build the LangGraph scoring workflow."""

    workflow = StateGraph(ScoringState)

    workflow.add_node("enrich_with_tech", enrich_with_tech)
    workflow.add_node("enrich_with_reddit", enrich_with_reddit)
    workflow.add_node("calculate_scores", calculate_scores)
    workflow.add_node("filter_qualified", filter_qualified)
    workflow.add_node("generate_talking_points", generate_talking_points)

    workflow.set_entry_point("enrich_with_tech")

    workflow.add_edge("enrich_with_tech", "enrich_with_reddit")
    workflow.add_edge("enrich_with_reddit", "calculate_scores")
    workflow.add_edge("calculate_scores", "filter_qualified")
    workflow.add_edge("filter_qualified", "generate_talking_points")
    workflow.add_edge("generate_talking_points", END)

    return workflow.compile()


def score_leads(
    leads: List[Dict[str, Any]], customer_config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Main function: Score leads based on intent signals.

    Args:
        leads: List of leads from Research Agent
        customer_config: Customer's ICP settings
            - competitors: List of competitor tools
            - target_tools: List of tools their ideal customers use
            - target_job_title: Role to find
            - min_signals: Minimum signals to qualify (default 1)
            - min_score: Minimum score to qualify (default 0)

    Returns:
        Dict with scored leads, stats, and recommendations
    """

    if not customer_config:
        customer_config = {}

    agent = build_scoring_agent()

    result = agent.invoke(
        {
            "leads": leads,
            "scored_leads": [],
            "customer_config": customer_config,
            "errors": [],
        }
    )

    # Calculate stats
    scored = result.get("scored_leads", [])
    unqualified = result.get("unqualified_leads", [])

    hot = [l for l in scored if l.get("tier") == "hot"]
    warm = [l for l in scored if l.get("tier") == "warm"]
    cold = [l for l in scored if l.get("tier") == "cold"]

    return {
        "scored_leads": scored,
        "unqualified_leads": unqualified,
        "reddit_signals": result.get("reddit_signals", []),
        "stats": {
            "total_input": len(leads),
            "qualified": len(scored),
            "unqualified": len(unqualified),
            "hot": len(hot),
            "warm": len(warm),
            "cold": len(cold),
            "avg_score": (
                round(sum(l.get("score", 0) for l in scored) / len(scored), 1)
                if scored
                else 0
            ),
        },
    }


if __name__ == "__main__":
    print("🎯 ExactFit Scoring Agent")
    print("=" * 50)

    # Test with sample leads
    test_leads = [
        {
            "company_name": "TechStartup Inc",
            "domain": "hubspot.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring 3 SDRs and 1 BDR",
        },
        {
            "company_name": "SalesForce Co",
            "domain": "salesforce.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring VP of Sales",
        },
        {
            "company_name": "SmallBiz",
            "domain": "example.com",
            "signal_type": "hiring",
            "signal_detail": "Hiring Marketing Manager",
        },
    ]

    # Customer config
    config = {
        "competitors": ["Apollo", "ZoomInfo", "Intercom"],
        "target_tools": ["HubSpot", "Salesforce"],
        "min_signals": 1,
    }

    print("\nScoring leads...")
    result = score_leads(test_leads, customer_config=config)

    print(f"\n📊 Stats:")
    print(f"   Total: {result['stats']['total_input']}")
    print(f"   Qualified: {result['stats']['qualified']}")
    print(f"   Hot: {result['stats']['hot']}")
    print(f"   Warm: {result['stats']['warm']}")
    print(f"   Cold: {result['stats']['cold']}")

    print(f"\n🎯 Scored Leads:")
    for lead in result["scored_leads"]:
        print(f"\n   {lead['tier_label']} {lead['company_name']} - {lead['score']}/100")
        print(f"   Signals ({lead['signal_count']}):")
        for signal in lead.get("signals", []):
            print(f"      • {signal['detail']} (+{signal['points']} pts)")

        if lead.get("talking_points"):
            print(f"   💬 Talking Points:")
            for tp in lead["talking_points"][:2]:
                print(f"      • {tp}")

        if lead.get("sample_opener"):
            print(f"   📝 Sample Opener:")
            print(f"      \"{lead['sample_opener'][:100]}...\"")
