import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
import re


def search_crunchbase(query: str = "SaaS", limit: int = 50) -> List[Dict[str, Any]]:
    """
    Search Crunchbase for companies.

    Args:
        query: Search term (e.g., "SaaS", "B2B", "AI")
        limit: Max results

    Returns:
        List of companies with funding info
    """

    # Crunchbase search URL
    url = f"https://www.crunchbase.com/discover/organization.companies"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    companies = []

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)

            if response.status_code != 200:
                # Try alternative: search via Google
                return search_crunchbase_via_google(query, limit)

            soup = BeautifulSoup(response.text, "html.parser")

            # Find company cards
            cards = soup.select("[class*='company'], [class*='organization']")

            for card in cards[:limit]:
                name_el = card.select_one("a, h3, h4")
                name = name_el.get_text(strip=True) if name_el else ""

                if name:
                    domain_guess = (
                        name.lower().replace(" ", "").replace(",", "")[:20] + ".com"
                    )

                    companies.append(
                        {
                            "company_name": name,
                            "domain": domain_guess,
                            "description": "",
                            "signal_type": "crunchbase_company",
                            "signal_detail": f"Found on Crunchbase",
                            "source_url": f"https://www.crunchbase.com/organization/{name.lower().replace(' ', '-')}",
                        }
                    )

    except Exception as e:
        print(f"Crunchbase error: {e}")
        return search_crunchbase_via_google(query, limit)

    return companies


def search_crunchbase_via_google(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fallback: Search Crunchbase via Google.
    """
    from services.search import google_search_sync

    companies = []

    try:
        search_query = f"site:crunchbase.com/organization {query} raised funding"
        results = google_search_sync(search_query, num_results=limit)

        for r in results:
            url = r.get("link", "")
            title = r.get("title", "")
            snippet = r.get("snippet", "")

            # Extract company name from URL or title
            if "/organization/" in url:
                slug = url.split("/organization/")[-1].split("/")[0].split("?")[0]
                name = slug.replace("-", " ").title()

                # Try to extract funding info from snippet
                funding_match = re.search(r"\$[\d.]+[MBK]", snippet)
                funding = funding_match.group(0) if funding_match else ""

                signal = f"Raised {funding}" if funding else "Crunchbase company"

                companies.append(
                    {
                        "company_name": name,
                        "domain": f"{slug.replace('-', '')}.com",
                        "description": snippet[:100],
                        "signal_type": "funding" if funding else "crunchbase_company",
                        "signal_detail": signal,
                        "source_url": url,
                    }
                )

    except Exception as e:
        print(f"Crunchbase Google search error: {e}")

    return companies


def get_recently_funded(
    funding_type: str = "Series A", limit: int = 30
) -> List[Dict[str, Any]]:
    """
    Find companies with recent funding rounds.

    Args:
        funding_type: "Seed", "Series A", "Series B", etc.
        limit: Max results
    """
    from services.search import search_news_sync

    companies = []

    try:
        query = f"{funding_type} funding announced startup"
        results = search_news_sync(query, num_results=limit)

        for r in results:
            title = r.get("title", "")
            snippet = r.get("snippet", "")

            # Try to extract company name (usually first capitalized words)
            name_match = re.search(r"^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)", title)
            name = name_match.group(1) if name_match else ""

            # Extract funding amount
            amount_match = re.search(r"\$[\d.]+[MBK]", title + " " + snippet)
            amount = amount_match.group(0) if amount_match else ""

            if name and len(name) > 2:
                domain_guess = name.lower().replace(" ", "") + ".com"

                companies.append(
                    {
                        "company_name": name,
                        "domain": domain_guess,
                        "description": snippet[:100],
                        "signal_type": "funding",
                        "signal_detail": (
                            f"Raised {amount} {funding_type}"
                            if amount
                            else f"Recent {funding_type}"
                        ),
                        "source_url": r.get("link", ""),
                    }
                )

    except Exception as e:
        print(f"Funding search error: {e}")

    return companies


if __name__ == "__main__":
    print("💰 Crunchbase Scraper Test")
    print("=" * 50)

    print("\nSearching for recently funded companies...\n")

    companies = get_recently_funded("Series A", limit=10)

    print(f"Found {len(companies)} companies:\n")

    for c in companies:
        print(f"  💰 {c['company_name']}")
        print(f"     Domain: {c['domain']}")
        print(f"     Signal: {c['signal_detail']}")
        print()
