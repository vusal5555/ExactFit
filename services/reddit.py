import os
import httpx
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()


def search_reddit(
    query: str, subreddits: List[str] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Search Reddit for posts mentioning a topic.
    Uses Reddit's public JSON API (no auth needed).

    Args:
        query: Search query (e.g., "Apollo alternative", "ZoomInfo sucks")
        subreddits: List of subreddits to search (e.g., ["sales", "SaaS"])
        limit: Max results to return

    Returns:
        List of relevant posts
    """

    headers = {"User-Agent": "ExactFit/1.0 (Intent Signal Finder)"}

    results = []

    # Default subreddits for B2B SaaS
    if not subreddits:
        subreddits = [
            "sales",
            "SaaS",
            "startups",
            "Entrepreneur",
            "smallbusiness",
            "B2B",
        ]

    try:
        with httpx.Client(timeout=15.0) as client:
            for subreddit in subreddits:
                if len(results) >= limit:
                    break

                # Reddit search API
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {
                    "q": query,
                    "restrict_sr": "on",  # Only this subreddit
                    "sort": "new",
                    "limit": min(limit, 25),
                }

                response = client.get(url, headers=headers, params=params)

                if response.status_code != 200:
                    continue

                data = response.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    parsed = parse_reddit_post(post.get("data", {}), subreddit)
                    if parsed:
                        results.append(parsed)

                        if len(results) >= limit:
                            break

        return results

    except Exception as e:
        print(f"Reddit search error: {e}")
        return []


def parse_reddit_post(post: Dict, subreddit: str) -> Dict[str, Any]:
    """
    Parse a single Reddit post.
    """

    try:
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        author = post.get("author", "")
        url = f"https://reddit.com{post.get('permalink', '')}"
        created = post.get("created_utc", 0)
        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)

        return {
            "title": title,
            "body": selftext[:500] if selftext else "",
            "author": author,
            "subreddit": subreddit,
            "url": url,
            "score": score,
            "num_comments": num_comments,
            "created_utc": created,
            "source": "reddit",
        }

    except Exception as e:
        return None


def find_competitor_mentions(competitor: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Find Reddit posts mentioning a competitor negatively or asking for alternatives.

    Args:
        competitor: Tool name (e.g., "Apollo", "Intercom")
        limit: Max results

    Returns:
        List of posts with intent signals
    """

    # Search queries that indicate buying intent
    intent_queries = [
        f"{competitor} alternative",
        f"{competitor} alternatives",
        f"better than {competitor}",
        f"replace {competitor}",
        f"leaving {competitor}",
        f"switch from {competitor}",
        f"{competitor} sucks",
        f"{competitor} expensive",
        f"{competitor} problems",
        f"hate {competitor}",
    ]

    all_results = []

    for query in intent_queries:
        if len(all_results) >= limit:
            break

        results = search_reddit(query, limit=5)

        for r in results:
            # Avoid duplicates
            if r["url"] not in [x["url"] for x in all_results]:
                r["competitor"] = competitor
                r["signal_type"] = "reddit_mention"
                r["signal_detail"] = f"Posted about {competitor} on r/{r['subreddit']}"
                all_results.append(r)

    return all_results[:limit]


def find_intent_signals(
    competitors: List[str], limit_per_competitor: int = 5
) -> List[Dict[str, Any]]:
    """
    Find Reddit posts showing intent to switch from competitors.

    Args:
        competitors: List of competitor names
        limit_per_competitor: Max results per competitor

    Returns:
        List of high-intent posts
    """

    all_signals = []

    for competitor in competitors:
        mentions = find_competitor_mentions(competitor, limit=limit_per_competitor)
        all_signals.extend(mentions)

    # Sort by score (most upvoted = most validated)
    all_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

    return all_signals


def find_buying_intent_posts(
    keywords: List[str] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Find Reddit posts showing general buying intent for sales/lead tools.

    Args:
        keywords: Custom keywords to search
        limit: Max results

    Returns:
        List of posts with buying intent
    """

    if not keywords:
        keywords = [
            "lead generation tool recommendation",
            "best sales intelligence tool",
            "looking for prospecting tool",
            "need better lead data",
            "email finder recommendation",
            "B2B data provider",
            "sales tool recommendation",
        ]

    all_results = []

    for keyword in keywords:
        if len(all_results) >= limit:
            break

        results = search_reddit(keyword, limit=5)

        for r in results:
            if r["url"] not in [x["url"] for x in all_results]:
                r["signal_type"] = "reddit_buying_intent"
                r["signal_detail"] = (
                    f"Asking for tool recommendations on r/{r['subreddit']}"
                )
                all_results.append(r)

    return all_results[:limit]


if __name__ == "__main__":
    print("🔍 Reddit Intent Signal Finder")
    print("=" * 50)

    # Test 1: Find competitor mentions
    print("\n--- Test 1: Apollo mentions ---")
    results = find_competitor_mentions("Apollo", limit=3)

    for r in results:
        print(f"\n📝 {r['title'][:60]}...")
        print(f"   Subreddit: r/{r['subreddit']}")
        print(f"   Score: {r['score']} | Comments: {r['num_comments']}")
        print(f"   URL: {r['url']}")

    # Test 2: Find buying intent
    print("\n--- Test 2: Buying intent posts ---")
    results = find_buying_intent_posts(limit=3)

    for r in results:
        print(f"\n📝 {r['title'][:60]}...")
        print(f"   Subreddit: r/{r['subreddit']}")
        print(f"   URL: {r['url']}")
