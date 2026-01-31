import os
import httpx
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()


def find_person(domain: str, role: str = "sales") -> Dict[str, Any]:
    """
    Find a person at a company using People Data Labs.

    Args:
        domain: Company domain (e.g., "acme.com")
        role: Role to search for (e.g., "sales", "vp sales")

    Returns:
        Dict with email, name, title, confidence
    """

    api_key = os.getenv("PEOPLE_DATA_LABS_API_KEY")

    if not api_key:
        raise ValueError("PEOPLE_DATA_LABS_API_KEY not configured in .env")

    url = "https://api.peopledatalabs.com/v5/person/search"

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    role_titles = {
        "sales": "VP Sales OR Head of Sales OR Sales Director OR Sales Manager",
        "vp_sales": "VP Sales OR Vice President Sales",
        "marketing": "VP Marketing OR Head of Marketing OR Marketing Director",
        "ceo": "CEO OR Chief Executive Officer OR Founder",
        "founder": "Founder OR Co-Founder OR CEO",
    }

    title_query = role_titles.get(role, role)

    payload = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"job_company_website": domain}},
                    {"match": {"job_title": title_query}},
                ]
            }
        },
        "size": 1,
    }

    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            if data.get("data") and len(data["data"]) > 0:
                person = data["data"][0]

                email = None

                if person.get("work_email"):
                    email = person["work_email"]
                elif person.get("emails") and len(person["emails"]) > 0:

                    for e in person["emails"]:
                        if (
                            isinstance(e, dict)
                            and e.get("type") == "current_professional"
                        ):
                            email = e.get("address")
                            break
                    if not email:
                        email = (
                            person["emails"][0]
                            if isinstance(person["emails"][0], str)
                            else person["emails"][0].get("address")
                        )
                return {
                    "email": email,
                    "first_name": person.get("first_name", ""),
                    "last_name": person.get("last_name", ""),
                    "title": person.get("job_title", ""),
                    "company": person.get("job_company_name", ""),
                    "linkedin_url": person.get("linkedin_url", ""),
                    "phone": person.get("mobile_phone", ""),
                    "source": "pdl",
                }
            return {"email": None, "source": "pdl", "error": "No person found"}

    except httpx.HTTPError as e:
        return {"email": None, "source": "pdl", "error": str(e)}


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
        raise ValueError("PEOPLE_DATA_LABS_API_KEY not configured in .env")

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    url = "https://api.peopledatalabs.com/v5/person/enrich"
    params = {"email": email}

    try:
        with httpx.Client() as client:
            response = client.get(url, headers=headers, params=params, timeout=10.0)

            if response.status_code == 404:
                return {"email": email, "valid": False, "error": "Email not found"}

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
                    "phone": person.get("mobile_phone", ""),
                    "source": "pdl",
                }
            return {"email": email, "valid": False, "error": "No data found"}
    except httpx.HTTPError as e:
        return {"email": email, "valid": False, "source": "pdl", "error": str(e)}
