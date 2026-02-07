import os
import httpx
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()


def find_person(domain: str, job_title: str = None) -> Dict[str, Any]:
    """
    Find a person at a company using People Data Labs.
    Works for ANY job title.

    Args:
        domain: Company domain (e.g., "acme.com")
        job_title: Target title (e.g., "Head of Support", "HR Manager", "VP Sales")

    Returns:
        Dict with email, name, title, confidence
    """
    api_key = os.getenv("PEOPLE_DATA_LABS_API_KEY")

    if not api_key:
        return {"email": None, "source": "pdl", "error": "API key not configured"}

    url = "https://api.peopledatalabs.com/v5/person/search"

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    # Build query based on job title
    if job_title:
        title_query = build_title_query(job_title)
    else:
        # Default: find any senior person
        title_query = "CEO OR Founder OR Director OR Manager OR Head OR VP"

    payload = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"job_company_website": domain}},
                    {"match": {"job_title": title_query}},
                ]
            }
        },
        "size": 5,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)

            if response.status_code == 404:
                return {"email": None, "source": "pdl", "error": "Not found"}

            response.raise_for_status()
            data = response.json()

            if data.get("data") and len(data["data"]) > 0:
                # Find best match if we have a specific title
                if job_title:
                    best = find_best_match(data["data"], job_title)
                else:
                    best = data["data"][0]

                # Get work email
                email = extract_email(best)

                return {
                    "email": email,
                    "first_name": best.get("first_name", ""),
                    "last_name": best.get("last_name", ""),
                    "title": best.get("job_title", ""),
                    "company": best.get("job_company_name", ""),
                    "linkedin_url": best.get("linkedin_url", ""),
                    "phone": best.get("mobile_phone", ""),
                    "source": "pdl",
                }

            return {"email": None, "source": "pdl", "error": "No person found"}

    except httpx.HTTPError as e:
        return {"email": None, "source": "pdl", "error": str(e)}


def build_title_query(job_title: str) -> str:
    """
    Build an Elasticsearch query for any job title.

    Args:
        job_title: Target title (e.g., "Head of Support", "HR Manager")

    Returns:
        Query string for PDL API
    """

    # Split title into words
    words = job_title.lower().replace("-", " ").split()

    # Remove common words
    stop_words = {"of", "the", "and", "a", "an", "at", "in", "for"}
    key_words = [w for w in words if w not in stop_words]

    if not key_words:
        return job_title

    # Build OR query with variations
    variations = []

    # Add the exact title
    variations.append(job_title)

    # Add variations with common prefixes
    prefixes = [
        "Head of",
        "VP of",
        "Vice President of",
        "Director of",
        "Manager of",
        "Lead",
    ]

    # Find the core role (last meaningful word usually)
    core_words = [
        w
        for w in key_words
        if w
        not in {
            "head",
            "vp",
            "vice",
            "president",
            "director",
            "manager",
            "lead",
            "senior",
            "chief",
        }
    ]

    if core_words:
        core_role = " ".join(core_words)
        for prefix in prefixes:
            variations.append(f"{prefix} {core_role}")

    # Add individual important words
    for word in key_words:
        if len(word) > 3:  # Skip short words
            variations.append(word)

    # Build OR query
    query = " OR ".join(variations)

    return query


def find_best_match(people: List[Dict], target_title: str) -> Dict:
    """
    Find the person whose title best matches the target.

    Args:
        people: List of people from PDL
        target_title: Title to match

    Returns:
        Best matching person
    """

    target_lower = target_title.lower()
    target_words = set(target_lower.replace("-", " ").split())

    stop_words = {"of", "the", "and", "a", "an", "at", "in", "for"}
    target_words = target_words - stop_words

    best_match = people[0]  # Default to first
    best_score = 0

    for person in people:
        title = person.get("job_title", "").lower()
        title_words = set(title.replace("-", " ").split()) - stop_words

        if not title_words:
            continue

        # Exact match
        if target_lower in title or title in target_lower:
            return person

        # Word overlap score
        matching = target_words & title_words
        score = len(matching) / max(len(target_words), 1)

        if score > best_score:
            best_score = score
            best_match = person

    return best_match


def extract_email(person: Dict) -> Optional[str]:
    """
    Extract work email from PDL person data.
    """

    # Try work_email first
    if person.get("work_email"):
        return person["work_email"]

    # Try emails list
    if person.get("emails") and len(person["emails"]) > 0:
        for e in person["emails"]:
            if isinstance(e, dict):
                if e.get("type") == "current_professional":
                    return e.get("address")
            elif isinstance(e, str):
                return e

        # Return first email as fallback
        first = person["emails"][0]
        if isinstance(first, dict):
            return first.get("address")
        return first

    return None


def enrich_email(email: str) -> Dict[str, Any]:
    """
    Enrich and verify an email address using PDL.

    Args:
        email: Email to verify

    Returns:
        Dict with person data if email is valid
    """
    api_key = os.getenv("PEOPLE_DATA_LABS_API_KEY")

    if not api_key:
        return {
            "email": email,
            "valid": False,
            "source": "pdl",
            "error": "API key not configured",
        }

    url = "https://api.peopledatalabs.com/v5/person/enrich"

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    params = {"email": email}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)

            if response.status_code == 404:
                return {
                    "email": email,
                    "valid": False,
                    "source": "pdl",
                    "error": "Not found",
                }

            response.raise_for_status()
            data = response.json()

            if data.get("data"):
                person = data["data"]
                return {
                    "email": email,
                    "valid": True,
                    "first_name": person.get("first_name", ""),
                    "last_name": person.get("last_name", ""),
                    "title": person.get("job_title", ""),
                    "company": person.get("job_company_name", ""),
                    "linkedin_url": person.get("linkedin_url", ""),
                    "source": "pdl",
                }

            return {"email": email, "valid": False, "source": "pdl", "error": "No data"}

    except httpx.HTTPError as e:
        return {"email": email, "valid": False, "source": "pdl", "error": str(e)}
