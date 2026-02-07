import os
import httpx
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()


def find_email(domain: str, job_title: str = None) -> Dict[str, Any]:
    """
    Find email for a decision maker at a company.

    Args:
        domain: Company domain (e.g., "acme.com")
        job_title: Target title (e.g., "Head of Support", "VP Sales", "HR Manager")

    Returns:
        Dict with email, name, position, confidence
    """
    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        return {"email": None, "source": "hunter", "error": "API key not configured"}

    # If specific job title provided, search and filter
    if job_title:
        return find_email_by_title(domain, job_title)

    # Otherwise just get any contact at the domain
    url = "https://api.hunter.io/v2/email-finder"

    params = {"domain": domain, "api_key": api_key}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)

            if response.status_code == 400:
                return {"email": None, "source": "hunter", "error": "Invalid request"}
            if response.status_code == 401:
                return {"email": None, "source": "hunter", "error": "Invalid API key"}
            if response.status_code == 429:
                return {"email": None, "source": "hunter", "error": "Rate limited"}
            if response.status_code == 404:
                return {"email": None, "source": "hunter", "error": "No email found"}

            response.raise_for_status()
            data = response.json()

            if data.get("data") and data["data"].get("email"):
                return {
                    "email": data["data"]["email"],
                    "first_name": data["data"].get("first_name", ""),
                    "last_name": data["data"].get("last_name", ""),
                    "position": data["data"].get("position", ""),
                    "confidence": data["data"].get("score", 0),
                    "source": "hunter",
                    "verified": data["data"].get("verification", {}).get("status")
                    == "valid",
                }

            return {"email": None, "source": "hunter", "error": "No email found"}

    except Exception as e:
        return {"email": None, "source": "hunter", "error": str(e)}


def find_email_by_title(domain: str, job_title: str) -> Dict[str, Any]:
    """
    Find email by searching for a specific job title.
    Works for ANY title: "VP Sales", "Head of Support", "HR Manager", etc.

    Args:
        domain: Company domain
        job_title: Target title to find

    Returns:
        Dict with email and contact info
    """

    # Get all contacts at the domain
    result = domain_search(domain, limit=10)

    if result.get("error") or not result.get("emails"):
        # Fallback to basic email finder
        return find_email(domain, job_title=None)

    # Find best match for the job title
    best_match = find_best_title_match(result["emails"], job_title)

    if best_match:
        return {
            "email": best_match["email"],
            "first_name": best_match.get("first_name", ""),
            "last_name": best_match.get("last_name", ""),
            "position": best_match.get("position", ""),
            "confidence": best_match.get("confidence", 0),
            "source": "hunter",
        }

    # No title match - return highest confidence contact
    if result["emails"]:
        first = result["emails"][0]
        return {
            "email": first["email"],
            "first_name": first.get("first_name", ""),
            "last_name": first.get("last_name", ""),
            "position": first.get("position", ""),
            "confidence": first.get("confidence", 0),
            "source": "hunter",
            "note": f"No exact match for '{job_title}', returned best available",
        }

    return {"email": None, "source": "hunter", "error": "No contacts found"}


def find_best_title_match(contacts: List[Dict], target_title: str) -> Optional[Dict]:
    """
    Find the contact whose title best matches the target.

    Args:
        contacts: List of contacts from domain_search
        target_title: Title to match (e.g., "Head of Support")

    Returns:
        Best matching contact or None
    """

    if not target_title:
        return None

    target_lower = target_title.lower()
    target_words = set(target_lower.replace("-", " ").split())

    # Remove common words that don't help matching
    stop_words = {"of", "the", "and", "a", "an", "at", "in", "for"}
    target_words = target_words - stop_words

    best_match = None
    best_score = 0

    for contact in contacts:
        # Handle None values
        position = contact.get("position") or ""
        position = position.lower()
        position_words = set(position.replace("-", " ").split()) - stop_words

        # Skip if no position
        if not position_words:
            continue

        # Check for exact match
        if target_lower in position or position in target_lower:
            return contact

        # Calculate word overlap
        matching_words = target_words & position_words
        score = len(matching_words) / max(len(target_words), 1)

        # Boost for key title words
        key_words = {
            "head",
            "vp",
            "vice",
            "president",
            "director",
            "manager",
            "chief",
            "lead",
            "senior",
        }
        if matching_words & key_words:
            score += 0.2

        if score > best_score:
            best_score = score
            best_match = contact

    # Only return if we have a reasonable match (>40% word overlap)
    if best_score >= 0.4:
        return best_match

    return None


def verify_email(email: str) -> Dict[str, Any]:
    """
    Verify if an email address is valid and deliverable.
    """
    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        return {"email": email, "status": "error", "error": "API key not configured"}

    url = "https://api.hunter.io/v2/email-verifier"
    params = {"email": email, "api_key": api_key}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)

            if response.status_code != 200:
                return {
                    "email": email,
                    "status": "error",
                    "error": f"HTTP {response.status_code}",
                }

            data = response.json()

            return {
                "email": email,
                "status": data["data"].get("status", "unknown"),
                "score": data["data"].get("score", 0),
                "deliverable": data["data"].get("status") == "valid",
            }
    except Exception as e:
        return {"email": email, "status": "error", "error": str(e)}


def domain_search(domain: str, limit: int = 5) -> Dict[str, Any]:
    """
    Find all emails at a domain.
    """
    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        return {"domain": domain, "emails": [], "error": "API key not configured"}

    url = "https://api.hunter.io/v2/domain-search"
    params = {"domain": domain, "api_key": api_key, "limit": limit}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)

            if response.status_code != 200:
                return {
                    "domain": domain,
                    "emails": [],
                    "error": f"HTTP {response.status_code}",
                }

            data = response.json()

            emails = []
            for person in data.get("data", {}).get("emails", []):
                emails.append(
                    {
                        "email": person.get("value"),
                        "first_name": person.get("first_name", ""),
                        "last_name": person.get("last_name", ""),
                        "position": person.get("position", ""),
                        "confidence": person.get("confidence", 0),
                        "department": person.get("department", ""),
                        "seniority": person.get("seniority", ""),
                    }
                )

            return {
                "domain": domain,
                "company": data.get("data", {}).get("organization", ""),
                "emails": emails,
                "total": len(emails),
            }
    except Exception as e:
        return {"domain": domain, "emails": [], "error": str(e)}
