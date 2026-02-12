import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any


def get_yc_companies(batch: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get companies from Y Combinator directory.

    Args:
        batch: Optional batch filter (e.g., "W24", "S23")
        limit: Max companies to return

    Returns:
        List of YC companies with domains
    """

    # YC company directory API (public)
    url = "https://api.ycombinator.com/v0.1/companies"

    params = {"page": 1, "per_page": limit}

    if batch:
        params["batch"] = batch

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    companies = []

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)

            if response.status_code != 200:
                # Fallback: scrape the website
                return scrape_yc_website(batch, limit)

            data = response.json()

            for company in data.get("companies", [])[:limit]:
                domain = company.get("website", "")
                if domain:
                    domain = (
                        domain.replace("https://", "")
                        .replace("http://", "")
                        .split("/")[0]
                    )

                companies.append(
                    {
                        "company_name": company.get("name", ""),
                        "domain": domain,
                        "description": company.get("one_liner", ""),
                        "batch": company.get("batch", ""),
                        "industry": company.get("industry", ""),
                        "team_size": company.get("team_size", 0),
                        "signal_type": "yc_company",
                        "signal_detail": f"Y Combinator {company.get('batch', '')} - {company.get('one_liner', '')[:50]}",
                        "source_url": f"https://www.ycombinator.com/companies/{company.get('slug', '')}",
                    }
                )

    except Exception as e:
        print(f"YC API error: {e}")
        return scrape_yc_website(batch, limit)

    return companies


def scrape_yc_website(batch: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fallback: Scrape YC website directly.
    """

    url = "https://www.ycombinator.com/companies"
    if batch:
        url += f"?batch={batch}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    companies = []

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)

            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.text, "html.parser")

            # Find company links
            company_links = soup.select("a[href*='/companies/']")

            seen = set()
            for link in company_links:
                href = link.get("href", "")

                # Skip navigation links
                if href in ["/companies", "/companies/"] or "?" in href:
                    continue

                # Extract company slug
                slug = href.replace("/companies/", "").strip("/")

                if slug and slug not in seen:
                    seen.add(slug)

                    name = link.get_text(strip=True)
                    if name:
                        companies.append(
                            {
                                "company_name": name,
                                "domain": f"{slug.replace('-', '')}.com",  # Guess domain
                                "description": "",
                                "batch": batch or "",
                                "signal_type": "yc_company",
                                "signal_detail": f"Y Combinator company",
                                "source_url": f"https://www.ycombinator.com{href}",
                            }
                        )

                if len(companies) >= limit:
                    break

    except Exception as e:
        print(f"YC scrape error: {e}")

    return companies


def get_recent_yc_batches() -> List[str]:
    """Get list of recent YC batches."""
    from datetime import datetime

    year = datetime.now().year
    short_year = str(year)[2:]
    prev_year = str(year - 1)[2:]

    # Return last 4 batches
    return [
        f"W{short_year}",  # Winter current year
        f"S{prev_year}",  # Summer last year
        f"W{prev_year}",  # Winter last year
        f"S{str(int(prev_year) - 1)}",  # Summer 2 years ago
    ]


if __name__ == "__main__":
    print("🚀 Y Combinator Scraper Test")
    print("=" * 50)

    companies = get_yc_companies(limit=10)

    print(f"Found {len(companies)} companies:\n")

    for c in companies:
        print(f"  🏢 {c['company_name']}")
        print(f"     Domain: {c['domain']}")
        print(f"     Batch: {c['batch']}")
        print(f"     Signal: {c['signal_detail'][:50]}")
        print()
