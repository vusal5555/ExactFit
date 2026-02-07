import httpx
from typing import Dict, Any, List


def generate_patterns(tool_name: str) -> List[str]:
    """
    Generate search patterns for any tool name.
    """
    name = tool_name.lower().strip()
    name_no_spaces = name.replace(" ", "")
    name_dashes = name.replace(" ", "-")

    patterns = [
        f"{name_no_spaces}.com/",
        f"{name_no_spaces}.io/",
        f"{name_no_spaces}.co/",
        f"cdn.{name_no_spaces}",
        f"js.{name_no_spaces}",
        f"widget.{name_no_spaces}",
        f"app.{name_no_spaces}",
        f"api.{name_no_spaces}",
        f"{name_no_spaces}cdn",
        f"{name_no_spaces}.js",
        f"/{name_no_spaces}/",
        f'"{name_no_spaces}"',
    ]

    if name_dashes != name_no_spaces:
        patterns.extend(
            [
                f"{name_dashes}.com/",
                f"{name_dashes}.io/",
            ]
        )

    return patterns


def detect_tool(html: str, tool_name: str) -> bool:
    """
    Check if HTML contains a specific tool.
    """
    patterns = generate_patterns(tool_name)

    for pattern in patterns:
        if pattern.lower() in html:
            return True

    return False


def get_tech_stack(domain: str, tools_to_detect: List[str] = None) -> Dict[str, Any]:
    """
    Detect technologies used by a website.

    Args:
        domain: Company domain (e.g., "acme.com")
        tools_to_detect: List of tools to look for (customer's competitors/target tools)

    Returns:
        Dict with detected tools
    """

    result = {"domain": domain, "detected_tools": [], "error": None}

    if not tools_to_detect:
        tools_to_detect = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(f"https://{domain}", headers=headers)

            if response.status_code != 200:
                result["error"] = f"HTTP {response.status_code}"
                return result

            html = response.text.lower()

            # Check for each tool the customer wants to detect
            for tool in tools_to_detect:
                if detect_tool(html, tool):
                    result["detected_tools"].append(tool)

    except Exception as e:
        result["error"] = str(e)

    return result


def detect_common_tools(domain: str) -> Dict[str, Any]:
    """
    Detect common B2B tools (fallback when customer doesn't specify).
    """

    common_tools = [
        # CRM
        "HubSpot",
        "Salesforce",
        "Pipedrive",
        "Zoho",
        # Sales Intelligence
        "Apollo",
        "ZoomInfo",
        "Lusha",
        "Clearbit",
        "Cognism",
        # Sales Engagement
        "Outreach",
        "SalesLoft",
        "Gong",
        # Support
        "Intercom",
        "Drift",
        "Zendesk",
        "Freshdesk",
        "Crisp",
        "Gorgias",
        "Tidio",
        # Marketing
        "Mailchimp",
        "Klaviyo",
        "Marketo",
        "ActiveCampaign",
        # Analytics
        "Mixpanel",
        "Amplitude",
        "Segment",
        "Heap",
        # Other
        "Stripe",
        "Slack",
        "Notion",
        "Monday",
    ]

    return get_tech_stack(domain, tools_to_detect=common_tools)
