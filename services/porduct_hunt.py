import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from datetime import datetime, timedelta


def get_recent_launches(days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent Product Hunt launches.
    New launches = companies actively growing = good leads.

    Args:
        days: Look back this many days
        limit: Max results

    Returns:
        List of recently launched companies
    """

    # Scrape Product Hunt (no API key needed)
    url = "https://www.producthunt.com"

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

            # Find product cards
            products = soup.select("[data-test='post-item']") or soup.select(
                "a[href*='/posts/']"
            )

            seen = set()
            for product in products:
                # Get product link
                link = (
                    product
                    if product.name == "a"
                    else product.select_one("a[href*='/posts/']")
                )

                if not link:
                    continue

                href = link.get("href", "")

                if href in seen or not href:
                    continue

                seen.add(href)

                # Get product name
                name_el = product.select_one("h3, h2, [class*='title']")
                name = name_el.get_text(strip=True) if name_el else ""

                # Get tagline
                tagline_el = product.select_one(
                    "p, [class*='tagline'], [class*='description']"
                )
                tagline = tagline_el.get_text(strip=True) if tagline_el else ""

                if name:
                    # Guess domain from product name
                    domain_guess = (
                        name.lower().replace(" ", "").replace("-", "") + ".com"
                    )

                    companies.append(
                        {
                            "company_name": name,
                            "domain": domain_guess,
                            "description": tagline,
                            "signal_type": "product_launch",
                            "signal_detail": f"Recently launched on Product Hunt: {tagline[:50]}",
                            "source_url": (
                                f"https://www.producthunt.com{href}"
                                if href.startswith("/")
                                else href
                            ),
                        }
                    )

                if len(companies) >= limit:
                    break

    except Exception as e:
        print(f"Product Hunt error: {e}")

    return companies


def get_top_products(period: str = "daily", limit: int = 30) -> List[Dict[str, Any]]:
    """
    Get top-voted products for a period.

    Args:
        period: "daily", "weekly", or "monthly"
        limit: Max results
    """

    url = f"https://www.producthunt.com/leaderboard/{period}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    companies = []

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)

            if response.status_code != 200:
                return get_recent_launches(limit=limit)  # Fallback

            soup = BeautifulSoup(response.text, "html.parser")

            # Find product items
            products = soup.select("a[href*='/posts/']")

            seen = set()
            for product in products:
                href = product.get("href", "")

                if href in seen or not href or href == "/posts":
                    continue

                seen.add(href)

                name = product.get_text(strip=True)

                # Skip navigation elements
                if len(name) < 2 or len(name) > 100:
                    continue

                domain_guess = (
                    name.lower().replace(" ", "").replace("-", "")[:20] + ".com"
                )

                companies.append(
                    {
                        "company_name": name,
                        "domain": domain_guess,
                        "description": "",
                        "signal_type": "product_launch",
                        "signal_detail": f"Top product on Product Hunt ({period})",
                        "source_url": f"https://www.producthunt.com{href}",
                    }
                )

                if len(companies) >= limit:
                    break

    except Exception as e:
        print(f"Product Hunt leaderboard error: {e}")

    return companies


if __name__ == "__main__":
    print("🚀 Product Hunt Scraper Test")
    print("=" * 50)

    companies = get_recent_launches(limit=10)

    print(f"Found {len(companies)} recent launches:\n")

    for c in companies:
        print(f"  🚀 {c['company_name']}")
        print(f"     Domain: {c['domain']}")
        print(f"     Signal: {c['signal_detail'][:50]}")
        print()
