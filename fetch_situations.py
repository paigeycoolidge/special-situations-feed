import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY    = os.getenv("NEWS_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

TODAY     = date.today().isoformat()
FEED_PATH = os.path.join(os.path.dirname(__file__), "feed_data", "feed.json")

HEADERS = {"User-Agent": "special-situations-feed contact@example.com"}

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
    "contingent value rights",
    "company dissolution liquidation",
]

# PR Newswire and GlobeNewswire RSS feeds for relevant categories
PRNEWSWIRE_FEEDS = [
    ("https://www.prnewswire.com/rss/news-releases-list.rss?category=MA",          "M&A"),
    ("https://www.prnewswire.com/rss/news-releases-list.rss?category=BC",          "Bankruptcy"),
    ("https://www.prnewswire.com/rss/news-releases-list.rss?category=FN",          "Financial"),
]

GLOBENEWSWIRE_FEEDS = [
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/merger",        "Merger"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/acquisition",   "Acquisition"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/bankruptcy",    "Bankruptcy"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/restructuring", "Restructuring"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/spin-off",      "Spin-off"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/liquidation",   "Liquidation"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/dissolution",   "Dissolution"),
    ("https://www.globenewswire.com/RssFeed/country/US/keyword/activist",      "Activist"),
]

SYSTEM_PROMPT = (
    "You are an event-driven special situations analyst at a hedge fund focused exclusively on corporate event catalysts. "
    "For each item, categorize it as exactly one of: ma, spin, distress, activist, cvr, dissolution. "
    "Use 'cvr' for contingent value rights, contingent basket rights, or milestone-based payouts tied to deal outcomes. "
    "Use 'dissolution' for company wind-downs, liquidations, plan of dissolution, or voluntary/involuntary liquidations. "
    "Then write a 2-3 sentence investment thesis covering: what the situation is, why it's interesting, and the key risk. "
    "Also rate the relevance of each situation to a special situations fund on a scale of 1-10. "
    "Be generous: any item involving a genuine corporate event catalyst — a deal, filing, restructuring, activist campaign, "
    "spin-off, liquidation, CVR, or bankruptcy — should score at least a 5. "
    "Reserve low scores (1-4) only for items with no identifiable security, no clear catalyst, or purely macro/thematic content. "
    "Score 7-10 for situations with a named public company, a clear near-term catalyst, and an investable angle. "
    "Return a JSON array of objects with fields: "
    "ticker, company, type, headline, thesis, source, signal (high/med/low), time, relevance_score (integer 1-10)."
)


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_edgar():
    results = []
    try:
        resp = requests.get(EDGAR_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit.get("_source", {})
            results.append({
                "headline": f"{src.get('file_date','')} — {src.get('form_type','')}: {src.get('display_names', [''])[0]}",
                "company":  src.get("display_names", [""])[0],
                "ticker":   src.get("ticker", ""),
                "source":   "SEC EDGAR",
                "time":     src.get("file_date", TODAY),
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
                    "q": query, "from": TODAY, "to": TODAY,
                    "language": "en", "sortBy": "publishedAt",
                    "pageSize": 20, "apiKey": NEWS_API_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            for a in resp.json().get("articles", []):
                url = a.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append({
                    "headline":    a.get("title", ""),
                    "company":     a.get("source", {}).get("name", ""),
                    "ticker":      "",
                    "source":      "NewsAPI",
                    "time":        (a.get("publishedAt") or TODAY)[:10],
                    "description": a.get("description", ""),
                })
        except Exception as e:
            print(f"[NewsAPI] Error for '{query}': {e}")

    print(f"[NewsAPI] {len(results)} articles fetched")
    return results


def _parse_rss(xml_text, source_label):
    """Parse RSS XML and return a list of raw items."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        # Handle both plain RSS and namespaced Atom-style RSS
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else root.findall("item")
        for item in entries:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link")  or "").strip()
            desc  = (item.findtext("description") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            # Rough date filter — keep items mentioning today or with no date
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(pub).date().isoformat()
                except Exception:
                    pub_date = TODAY
            else:
                pub_date = TODAY
            items.append({
                "headline":    title,
                "company":     "",
                "ticker":      "",
                "source":      source_label,
                "time":        pub_date,
                "description": re.sub(r"<[^>]+>", "", desc)[:300],
                "url":         link,
            })
    except ET.ParseError as e:
        print(f"[RSS] XML parse error for {source_label}: {e}")
    return items


def fetch_prnewswire():
    results = []
    seen = set()
    for url, label in PRNEWSWIRE_FEEDS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            items = _parse_rss(resp.text, f"PR Newswire ({label})")
            for item in items:
                key = item["headline"][:80]
                if key not in seen:
                    seen.add(key)
                    results.append(item)
        except Exception as e:
            print(f"[PRNewswire] Error for {label}: {e}")
    print(f"[PRNewswire] {len(results)} releases fetched")
    return results


def fetch_globenewswire():
    results = []
    seen = set()
    for url, label in GLOBENEWSWIRE_FEEDS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            items = _parse_rss(resp.text, f"GlobeNewswire ({label})")
            for item in items:
                key = item["headline"][:80]
                if key not in seen:
                    seen.add(key)
                    results.append(item)
        except Exception as e:
            print(f"[GlobeNewswire] Error for {label}: {e}")
    print(f"[GlobeNewswire] {len(results)} releases fetched")
    return results


# ── Deduplication ─────────────────────────────────────────────────────────────

def normalize_key(item):
    ticker  = (item.get("ticker") or "").strip().upper()
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


# ── Claude analysis + relevance filtering ─────────────────────────────────────

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


BATCH_SIZE = 40


def _parse_claude_response(raw_text):
    """Extract a JSON array from Claude's response, handling markdown code blocks."""
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def analyze_with_claude(items):
    if not items:
        print("[Claude] No items to analyze")
        return []

    client  = Anthropic(api_key=ANTHROPIC_API_KEY)
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    all_results = []

    print(f"[Claude] Sending {len(items)} items in {len(batches)} batches of up to {BATCH_SIZE}...")

    for idx, batch in enumerate(batches, 1):
        print(f"[Claude] Batch {idx}/{len(batches)} ({len(batch)} items)...")
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(batch)}],
            )
            parsed = _parse_claude_response(response.content[0].text)
            if parsed:
                all_results.extend(parsed)
            else:
                print(f"[Claude] Batch {idx}: could not parse response")
                print(response.content[0].text[:300])
        except Exception as e:
            print(f"[Claude] Batch {idx} error: {e}")

    print(f"[Claude] {len(all_results)} situations analyzed across all batches")
    return all_results


def filter_by_relevance(situations, min_score=6):
    filtered = [s for s in situations if int(s.get("relevance_score", 0)) >= min_score]
    dropped  = len(situations) - len(filtered)
    print(f"[Filter] {len(situations)} -> {len(filtered)} situations (dropped {dropped} below score {min_score})")
    return filtered


# ── Output ────────────────────────────────────────────────────────────────────

def save_feed(situations):
    output = {
        "date":          TODAY,
        "run_timestamp": datetime.utcnow().isoformat() + "Z",
        "count":         len(situations),
        "situations":    situations,
    }
    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    with open(FEED_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Feed] Saved {len(situations)} situations to {FEED_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Special Situations Feed — {TODAY} ===")

    all_items = (
        fetch_edgar()
        + fetch_news()
        + fetch_prnewswire()
        + fetch_globenewswire()
    )

    deduped    = deduplicate(all_items)
    analyzed   = analyze_with_claude(deduped)
    situations = filter_by_relevance(analyzed, min_score=5)

    save_feed(situations)
    print("=== Done ===")


if __name__ == "__main__":
    main()
