import os
import httpx
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


async def google_search(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """
    Search Google using Serper API.

    Args:
        query: Search query
        num_results: Number of results

    Returns:
        List of search results with title, link, snippet
    """
    api_key = os.getenv("SERPER_API_KEY")

    if not api_key:
        raise ValueError("SERPER_API_KEY not configured in .env")

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": num_results}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        return data.get("organic", [])


def google_search_sync(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """Sync version using httpx."""
    api_key = os.getenv("SERPER_API_KEY")

    if not api_key:
        raise ValueError("SERPER_API_KEY not configured in .env")

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": num_results}

    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        return data.get("organic", [])


async def search_news(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search Google News using Serper API.

    Good for finding recent funding announcements, company news.
    """
    api_key = os.getenv("SERPER_API_KEY")

    if not api_key:
        raise ValueError("SERPER_API_KEY not configured in .env")

    url = "https://google.serper.dev/news"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": num_results}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        return data.get("news", [])
