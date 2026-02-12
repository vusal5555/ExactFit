from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from services.builtwith import get_tech_stack
from services.reddit import find_competitor_mentions
from services.llm import invoke_llm
import json


class ScoringState(TypedDict):
    leads: List[Dict[str, Any]]
    scored_leads: List[Dict[str, Any]]
    customer_config: Dict[str, Any]
    errors: List[str]


# Signal weights (from feedback)
SIGNAL_WEIGHTS = {
    "hiring_sales": 40,
    "hiring_multiple": 10,
    "hiring_leadership": 35,
    "funding": 40,
    "tech_competitor": 15,
    "tech_target": 10,
    "reddit_mention": 30,
    "reddit_buying_intent": 35,
    "g2_complaint": 40,
    "growth_signal": 25,
    "combo_bonus": 10,
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

        if all_tools:
            tech_result = get_tech_stack(domain, tools_to_detect=all_tools)
        else:
            tech_result = {"detected_tools": [], "error": None}

        detected = tech_result.get("detected_tools", [])

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

    reddit_signals = {}
    for competitor in competitors:
        mentions = find_competitor_mentions(competitor, limit=10)
        for mention in mentions:
            reddit_signals[mention["url"]] = mention

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

        signal_type = lead.get("signal_type", "")
        signal_detail = lead.get("signal_detail", "").lower()

        if signal_type == "hiring":
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

        if len(signals) >= 3:
            score += SIGNAL_WEIGHTS["combo_bonus"]
            signals.append(
                {
                    "type": "combo_bonus",
                    "points": SIGNAL_WEIGHTS["combo_bonus"],
                    "detail": f"Multiple signals detected ({len(signals)})",
                }
            )

        score = min(score, 100)

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

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {**state, "scored_leads": scored}


def filter_qualified(state: ScoringState) -> ScoringState:
    """Node 4: Filter leads with minimum signals."""

    config = state.get("customer_config", {})
    min_signals = config.get("min_signals", 1)
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


def generate_talking_points_llm(lead: Dict) -> List[str]:
    """Use LLM to generate personalized talking points."""

    signals = lead.get("signals", [])

    if not signals:
        return []

    signals_text = "\n".join([f"- {s['detail']}" for s in signals])

    prompt = """You are a B2B sales expert. Generate 3 specific talking points 
    for reaching out to this company.

    Company: {company_name}
    Contact: {contact_name} ({contact_title})
    Signals detected:
    {signals}

    Rules:
    - Be specific to their situation, not generic
    - Reference the actual signals detected
    - Keep each point to 1 sentence
    - Focus on how you can help them

    Return exactly 3 talking points, one per line, starting with "•"."""

    try:
        result = invoke_llm(
            system_prompt=prompt.format(
                company_name=lead.get("company_name", "the company"),
                contact_name=lead.get("contact_name", "the contact"),
                contact_title=lead.get("contact_title", ""),
                signals=signals_text,
            ),
            user_message="Generate 3 talking points",
        )

        # Parse bullet points
        points = []
        for line in result.strip().split("\n"):
            line = line.strip()
            if line.startswith("•"):
                points.append(line[1:].strip())
            elif line.startswith("-"):
                points.append(line[1:].strip())
            elif line:
                points.append(line)

        return points[:3]

    except Exception as e:
        # Fallback to simple template
        return [f"Reference: {s['detail']}" for s in signals[:3]]


def generate_opener_llm(lead: Dict) -> str:
    """Use LLM to generate personalized email opener."""

    signals = lead.get("signals", [])

    if not signals:
        return ""

    signals_text = "\n".join([f"- {s['detail']}" for s in signals])

    prompt = """You are a B2B sales expert writing a cold email opener.

    Company: {company_name}
    Contact: {contact_name} ({contact_title})
    Signals detected:
    {signals}

    Rules:
    - Write exactly 2 sentences
    - Reference their specific situation (use the signals)
    - Don't be salesy, be helpful and genuine
    - Sound human, not like AI
    - Don't use phrases like "I noticed" or "I came across"
    - Start with something specific about them

    Write the opener paragraph only, no subject line or greeting."""

    try:
        result = invoke_llm(
            system_prompt=prompt.format(
                company_name=lead.get("company_name", "your company"),
                contact_name=lead.get("contact_name", ""),
                contact_title=lead.get("contact_title", ""),
                signals=signals_text,
            ),
            user_message="Write a 2-sentence cold email opener",
        )

        return result.strip()

    except Exception as e:
        # Fallback to simple template
        company = lead.get("company_name", "your company")
        signal = signals[0].get("detail", "") if signals else ""
        return f"Saw {company} is {signal.lower()} - congrats on the growth! When teams scale, they usually hit data quality issues fast."


def generate_talking_points(state: ScoringState) -> ScoringState:
    """Node 5: Generate personalized talking points and openers using LLM."""

    for lead in state["scored_leads"]:
        # Generate talking points with LLM
        lead["talking_points"] = generate_talking_points_llm(lead)

        # Generate opener with LLM
        lead["sample_opener"] = generate_opener_llm(lead)

    return state


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
