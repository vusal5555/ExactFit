import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Tuple, Dict, List
from urllib.parse import urljoin


async def scrape_page(url: str) -> Tuple[str, Dict[str, str]]:
    """
    Scrape a webpage and return text content + extracted links.

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

    for element in soup(["script", "style", "noscript", "nav", "footer"]):
        element.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    links = extract_links(soup, url)

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


def extract_domain_from_url(url: str) -> str:
    """Extract clean domain from URL."""

    domain = url.replace("http://", "").replace("https://", "")
    domain = domain.replace("www.", "")
    domain = domain.split("/")[0]
    domain = domain.split("?")[0]
    return domain.lower()


def is_company_website(url: str) -> bool:
    """Check if URL is likely a company website."""

    if not url or not url.startswith("http"):
        return False

    url_lower = url.lower()

    excluded = [
        "greenhouse.io",
        "lever.co",
        "indeed.com",
        "linkedin.com",
        "glassdoor.com",
        "wellfound.com",
        "builtin.com",
        "angel.co",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
        "github.com",
        "medium.com",
        "crunchbase.com",
        "techcrunch.com",
        "google.com",
        "apple.com/app",
        "play.google.com",
        "apps.apple.com",
        "bit.ly",
        "t.co",
        "mailto:",
        "tel:",
        "javascript:",
        ".gov",
        ".edu",
        "dol.gov",
    ]

    for site in excluded:
        if site in url_lower:
            return False

    return True


def extract_email_domain(soup: BeautifulSoup) -> Optional[str]:
    """Extract company domain from email addresses on page."""

    mailto_links = soup.find_all("a", href=lambda x: x and x.startswith("mailto:"))

    for link in mailto_links:
        link: BeautifulSoup = link
        href = link.get("href", "")
        email = href.replace("mailto:", "").split("?")[0]

    if "@" in email:
        domain = email.split("@")[1].lower()

        generic = [
            "gmail.com",
            "yahoo.com",
            "outlook.com",
            "hotmail.com",
        ]

        if domain not in generic:
            return domain

    text = soup.get_text()
    email_pattern = r"[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
    matches = re.findall(email_pattern, text)

    for domain in matches:
        domain = domain.lower()

        generic = [
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "greenhouse.io",
            "lever.co",
        ]

        if domain not in generic:
            return domain

    return None


def extract_company_website(job_page_url: str) -> Optional[str]:
    """
    Scrape a job posting page to find the real company website.
    """

    if "linkedin.com" in job_page_url:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # Extract company slug from URL
    company_slug = None
    if "greenhouse.io/" in job_page_url:
        parts = job_page_url.split("greenhouse.io/")
        if len(parts) > 1:
            company_slug = parts[1].split("/")[0]
    elif "lever.co/" in job_page_url:
        parts = job_page_url.split("lever.co/")
        if len(parts) > 1:
            company_slug = parts[1].split("/")[0]

    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(job_page_url, headers=headers)
            response.raise_for_status()
    except Exception:
        # Fallback to slug
        if company_slug:
            return f"{company_slug}.com"
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Method 1: Try to find email domain (most reliable)
    email_domain = extract_email_domain(soup)
    if email_domain:
        return email_domain

    # Method 2: Look for links with company website indicators
    all_links = soup.find_all("a", href=True)

    candidates: List[Tuple[int, str]] = []

    for link in all_links:
        href = link.get("href", "")

        if not is_company_website(href):
            continue

        domain = extract_domain_from_url(href)

        if not domain or "." not in domain or len(domain) < 4:
            continue

        # Score the link
        score = 0
        link_text = link.get_text(strip=True).lower()

        # Company slug match
        if company_slug:
            slug_clean = company_slug.lower().replace("-", "").replace("_", "")
            domain_clean = domain.replace("-", "").replace(".", "").replace("_", "")
            if slug_clean in domain_clean:
                score += 50

        # Link text indicators
        if any(word in link_text for word in ["website", "visit", "home", "about"]):
            score += 30

        # Penalize deep paths
        path_depth = href.count("/") - 2
        if path_depth > 2:
            score -= 10

        candidates.append((score, domain))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Method 3: Fallback to company slug
    if company_slug:
        return f"{company_slug}.com"

    return None
