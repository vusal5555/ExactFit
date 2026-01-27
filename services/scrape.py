import re
import httpx
from bs4 import BeautifulSoup
from typing import Tuple, Dict
from urllib.parse import urljoin


async def scrape_page(url: str) -> Tuple[str, Dict[str, str]]:
    """
    Scrape a webpage and return text content + extracted links.

    Returns:
        Tuple of (text_content, links_dict)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except Exception as e:
        return f"Error scraping {url}: {str(e)}", {}

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "noscript", "nav", "footer"]):
        element.decompose()

    # Extract text
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Extract important links
    links = extract_links(soup, url)

    # Limit length
    if len(text) > 15000:
        text = text[:15000] + "\n\n[Truncated...]"

    return text, links


def extract_links(soup: BeautifulSoup, base_url: str) -> Dict[str, str]:
    """Extract careers, blog, and social links from page."""
    links = {"careers": "", "blog": "", "twitter": "", "linkedin": "", "facebook": ""}

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").lower()
        full_url = urljoin(base_url, anchor.get("href", ""))

        if "/careers" in href or "/jobs" in href:
            links["careers"] = full_url
        elif "/blog" in href or "/news" in href:
            links["blog"] = full_url
        elif "twitter.com" in href or "x.com" in href:
            links["twitter"] = full_url
        elif "linkedin.com" in href:
            links["linkedin"] = full_url
        elif "facebook.com" in href:
            links["facebook"] = full_url

    return links


async def scrape_careers_page(domain: str) -> str:
    """Try to find and scrape a company's careers page."""
    possible_urls = [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://careers.{domain}",
        f"https://{domain}/about/careers",
    ]

    for url in possible_urls:
        content, _ = await scrape_page(url)
        if not content.startswith("Error"):
            return content

    return "No careers page found"
