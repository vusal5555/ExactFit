import os
import httpx
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


def find_email(domain: str, role: str = "sales") -> Dict[str, Any]:
    """
    Find email for a decision maker at a company.

    Args:
        domain: Company domain (e.g., "acmecorp.com")
        role: Role to search for (not used in basic API, kept for compatibility)

    Returns:
        Dict with email, name, position, confidence
    """
    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        raise ValueError("HUNTER_API_KEY not configured in .env")

    url = "https://api.hunter.io/v2/email-finder"

    # Basic params only - department/seniority requires paid plan
    params = {"domain": domain, "api_key": api_key}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)

            # Handle specific errors
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

    except httpx.HTTPError as e:
        return {"email": None, "source": "hunter", "error": str(e)}


def verify_email(email: str) -> Dict[str, Any]:
    """
    Verify if an email address is valid and deliverable.

    """

    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        raise ValueError("HUNTER_API_KEY not configured in .env")

    url = "https://api.hunter.io/v2/email-verifier"
    params = {"email": email, "api_key": api_key}

    try:
        with httpx.Client() as client:
            response = client.get(url=url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            return {
                "email": email,
                "status": data["data"].get("status"),
                "score": data["data"].get("score", 0),
                "deliverable": data["data"].get("status") == "valid",
            }
    except httpx.HTTPError as e:
        return {"email": email, "status": "error", "error": str(e)}


def domain_search(domain: str, limit: int = 5) -> Dict[str, Any]:
    """
    Find all emails at a domain.
    """

    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        raise ValueError("HUNTER_API_KEY not configured in .env")

    url = "https://api.hunter.io/v2/domain-search"

    params = {"domain": domain, "api_key": api_key, "limit": limit}

    try:
        with httpx.Client() as client:
            response = client.get(url=url, params=params, timeout=10.0)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()

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
    except httpx.HTTPError as e:
        raise RuntimeError(f"Hunter.io API error: {str(e)}")
