import json
import os
import re
from datetime import date, datetime

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

TODAY = date.today().isoformat()
FEED_PATH = os.path.join(os.path.dirname(__file__), "feed_data", "feed.json")

EDGAR_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    f"?q=&dateRange=custom&startdt={TODAY}&enddt={TODAY}"
    "&forms=SC+13D,8-K,S-4,10-12B"
)

NEWS_QUERIES = [
    "merger acquisition",
    "bankruptcy filing",
    "activist investor",
    "spin-off",
]

SYSTEM_PROMPT = (
    "You are an event-driven special situations analyst at a hedge fund. "
    "For each item, categorize it as one of: ma, spin, distress, activist. "
    "Then write a 2-3 sentence investment thesis covering: what the situation is, "
    "why it's interesting, and the key risk. "
    "Return a JSON array of objects with fields: "
    "ticker, company, type, headline, thesis, source, signal (high/med/low), time."
)


def fetch_edgar():
    results = []
    try:
        resp = requests.get(EDGAR_URL, headers={"User-Agent": "special-situations-feed contact@example.com"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit.get("_source", {})
            results.append({
                "headline": src.get("file_date", "") + " — " + src.get("form_type", "") + ": " + src.get("display_names", [""])[0],
                "company": src.get("display_names", [""])[0],
                "ticker": src.get("ticker", ""),
                "source": "SEC EDGAR",
                "time": src.get("file_date", TODAY),
                "form": src.get("form_type", ""),
                "raw": src,
            })
    except Exception as e:
        print(f"[EDGAR] Error: {e}")
    print(f"[EDGAR] {len(results)} filings fetched")
    return results


def fetch_news():
    if not NEWS_API_KEY:
        print("[NewsAPI] NEWS_API_KEY not set, skipping")
        return []

    results = []
    seen_urls = set()

    for query in NEWS_QUERIES:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": TODAY,
                    "to": TODAY,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "apiKey": NEWS_API_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            for a in articles:
                url = a.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append({
                    "headline": a.get("title", ""),
                    "company": a.get("source", {}).get("name", ""),
                    "ticker": "",
                    "source": "NewsAPI",
                    "time": (a.get("publishedAt") or TODAY)[:10],
                    "url": url,
                    "description": a.get("description", ""),
                    "query": query,
                })
        except Exception as e:
            print(f"[NewsAPI] Error for query '{query}': {e}")

    print(f"[NewsAPI] {len(results)} articles fetched")
    return results


def normalize_key(item):
    ticker = (item.get("ticker") or "").strip().upper()
    company = re.sub(r"\s+", " ", (item.get("company") or "")).strip().lower()
    headline = (item.get("headline") or "").strip().lower()
    if ticker:
        return ticker
    if company:
        return company
    return headline[:80]


def deduplicate(items):
    seen = {}
    for item in items:
        key = normalize_key(item)
        if key and key not in seen:
            seen[key] = item
    deduped = list(seen.values())
    print(f"[Dedup] {len(items)} -> {len(deduped)} items after deduplication")
    return deduped


def build_user_message(items):
    lines = []
    for i, item in enumerate(items, 1):
        parts = [f"{i}. [{item['source']}]", item.get("headline", "")]
        if item.get("ticker"):
            parts.append(f"Ticker: {item['ticker']}")
        if item.get("company"):
            parts.append(f"Company: {item['company']}")
        if item.get("description"):
            parts.append(item["description"])
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


def analyze_with_claude(items):
    if not items:
        print("[Claude] No items to analyze")
        return []

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    user_message = build_user_message(items)

    print(f"[Claude] Sending {len(items)} items for analysis...")
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text.strip()

    # Extract JSON array from response
    match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if not match:
        print("[Claude] Could not extract JSON array from response")
        print(raw_text[:500])
        return []

    try:
        analyzed = json.loads(match.group())
        print(f"[Claude] {len(analyzed)} situations analyzed")
        return analyzed
    except json.JSONDecodeError as e:
        print(f"[Claude] JSON parse error: {e}")
        return []


def save_feed(situations):
    output = {
        "date": TODAY,
        "run_timestamp": datetime.utcnow().isoformat() + "Z",
        "count": len(situations),
        "situations": situations,
    }
    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    with open(FEED_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Feed] Saved {len(situations)} situations to {FEED_PATH}")


def main():
    print(f"=== Special Situations Feed — {TODAY} ===")

    edgar_items = fetch_edgar()
    news_items = fetch_news()

    all_items = edgar_items + news_items
    deduped = deduplicate(all_items)

    situations = analyze_with_claude(deduped)
    save_feed(situations)

    print("=== Done ===")


if __name__ == "__main__":
    main()
