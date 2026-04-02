import hashlib
import json
import os
import re
import smtplib
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.mime.text import MIMEText

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY    = os.getenv("NEWS_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

TODAY      = date.today().isoformat()
FEED_PATH  = os.path.join(os.path.dirname(__file__), "feed_data", "feed.json")
SEEN_PATH  = os.path.join(os.path.dirname(__file__), "feed_data", "seen_items.json")

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
    "Each input item includes a URL field. Copy it exactly as-is into the source_url field of your output — do not modify, shorten, or omit it. "
    "Return a JSON array of objects with fields: "
    "ticker, company, type, headline, thesis, source, source_url, signal (high/med/low), time, relevance_score (integer 1-10)."
)


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_edgar():
    results = []
    try:
        resp = requests.get(EDGAR_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        for hit in hits:
            src      = hit.get("_source", {})
            cik      = src.get("entity_id", "")
            form     = src.get("form_type", "")
            company  = src.get("display_names", [""])[0]
            # Link to the company's filing page on EDGAR
            source_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"
                if cik else "https://www.sec.gov/cgi-bin/browse-edgar"
            )
            results.append({
                "headline":   f"{src.get('file_date','')} — {form}: {company}",
                "company":    company,
                "ticker":     src.get("ticker", ""),
                "source":     "SEC EDGAR",
                "time":       src.get("file_date", TODAY),
                "source_url": source_url,
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
                    "source_url":  a.get("url", ""),
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
                "source_url":  link,
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


def fetch_courtlistener():
    results = []
    try:
        resp = requests.get(
            "https://www.courtlistener.com/api/rest/v3/dockets/",
            params={"type": 1, "order_by": "-date_filed", "chapter": 11, "page_size": 30},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        for case in resp.json().get("results", []):
            case_name   = case.get("case_name") or ""
            date_filed  = (case.get("date_filed") or TODAY)[:10]
            court       = case.get("court_id") or ""
            docket_url  = "https://www.courtlistener.com" + (case.get("absolute_url") or "")
            results.append({
                "headline":    f"Chapter 11: {case_name} ({court})",
                "company":     case_name,
                "ticker":      "",
                "source":      "CourtListener",
                "time":        date_filed,
                "description": f"Chapter 11 bankruptcy filed in {court}. Docket: {case.get('docket_number','')}",
                "source_url":  docket_url,
            })
    except Exception as e:
        print(f"[CourtListener] Error: {e}")
    print(f"[CourtListener] {len(results)} cases fetched")
    return results


def fetch_seekingalpha():
    results = []
    seen = set()
    sa_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    pages = [
        ("https://seekingalpha.com/market-news/mergers-acquisitions", "Seeking Alpha (M&A)"),
        ("https://seekingalpha.com/market-news/restructuring",        "Seeking Alpha (Restructuring)"),
    ]
    for url, label in pages:
        try:
            resp = requests.get(url, headers=sa_headers, timeout=15)
            # SA embeds article data as JSON in <script id="__NEXT_DATA__">
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
            if match:
                data      = json.loads(match.group(1))
                articles  = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("marketNewsStories", [])
                    or data.get("props", {})
                        .get("pageProps", {})
                        .get("initialState", {})
                        .get("marketNews", {})
                        .get("items", [])
                )
                for a in articles:
                    title    = a.get("title") or a.get("headline") or ""
                    slug     = a.get("uri") or a.get("slug") or ""
                    pub_date = (a.get("publish_on") or a.get("publishedAt") or TODAY)[:10]
                    art_url  = f"https://seekingalpha.com{slug}" if slug.startswith("/") else f"https://seekingalpha.com/article/{slug}"
                    key      = title[:80]
                    if title and key not in seen:
                        seen.add(key)
                        results.append({
                            "headline":    title,
                            "company":     "",
                            "ticker":      "",
                            "source":      label,
                            "time":        pub_date,
                            "description": "",
                            "source_url":  art_url,
                        })
            else:
                # Fallback: parse <h3>/<a> tags from the HTML
                for m in re.finditer(r'href="(/news/\d+[^"]*)"[^>]*>([^<]{10,})<', resp.text):
                    art_url = "https://seekingalpha.com" + m.group(1)
                    title   = m.group(2).strip()
                    key     = title[:80]
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "headline":   title,
                            "company":    "",
                            "ticker":     "",
                            "source":     label,
                            "time":       TODAY,
                            "source_url": art_url,
                        })
        except Exception as e:
            print(f"[SeekingAlpha] Error for {label}: {e}")
    print(f"[SeekingAlpha] {len(results)} articles fetched")
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
        if item.get("source_url"):
            parts.append(f"URL: {item['source_url']}")
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


BATCH_SIZE = 40

PREFILTER_KEYWORDS = [
    "merger", "acquisition", "acqui", "takeover",
    "spin-off", "spinoff", "spin off",
    "bankruptcy", "chapter 11", "chapter11", "insolvent", "going concern",
    "activist", "13d", "13-d",
    "tender offer",
    "liquidation", "dissolution", "wind down", "wind-down",
    "cvr", "contingent value",
    "restructuring", "restructure",
    "going private", "take-private", "take private",
    "special committee", "strategic review", "strategic alternatives",
    "leveraged buyout", "lbo", "management buyout", "mbo",
    "delist", "delisting",
]

MAX_CLAUDE_ITEMS = 40


def keyword_prefilter(items):
    """Keep items whose headline contains at least one high-signal keyword.
    Score by number of keyword matches so we can rank when capping at MAX_CLAUDE_ITEMS."""
    def score(item):
        text = (item.get("headline", "") + " " + item.get("description", "")).lower()
        return sum(1 for kw in PREFILTER_KEYWORDS if kw in text)

    scored = [(score(item), item) for item in items]
    matched = [(s, item) for s, item in scored if s > 0]
    dropped = len(items) - len(matched)
    print(f"[Prefilter] {len(items)} -> {len(matched)} items after keyword filter (dropped {dropped})")

    # Sort by match strength descending, cap at MAX_CLAUDE_ITEMS
    matched.sort(key=lambda x: x[0], reverse=True)
    capped = [item for _, item in matched[:MAX_CLAUDE_ITEMS]]
    if len(matched) > MAX_CLAUDE_ITEMS:
        print(f"[Prefilter] Capped at {MAX_CLAUDE_ITEMS} (dropped {len(matched) - MAX_CLAUDE_ITEMS} lower-scoring matches)")
    return capped


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


def send_credit_alert():
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = "".join(c for c in (os.getenv("GMAIL_APP_PASSWORD") or "") if c.isascii()).replace(" ", "")
    recipient = os.getenv("RECIPIENT_EMAIL")
    if not all([gmail_user, gmail_password, recipient]):
        print("[Alert] Cannot send credit alert — email credentials not set")
        return
    msg = MIMEText(
        "Your Anthropic API credit balance has been exhausted.\n\n"
        "The Special Situations Feed could not analyze today's items.\n\n"
        "Please top up your credits at:\n"
        "https://console.anthropic.com/settings/billing\n\n"
        "— Special Situations Feed"
    )
    msg["Subject"] = "⚠️ Action needed: Anthropic API credits exhausted"
    msg["From"] = gmail_user
    msg["To"] = recipient
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, recipient, msg.as_string())
        print("[Alert] Credit exhaustion alert sent")
    except Exception as e:
        print(f"[Alert] Failed to send credit alert: {e}")


def analyze_with_claude(items):
    if not items:
        print("[Claude] No items to analyze")
        return []

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("[Claude] ANTHROPIC_API_KEY is not set — cannot analyze items")

    # Test connectivity to api.anthropic.com before attempting any batches
    print("[Claude] Testing connectivity to api.anthropic.com...")
    try:
        probe = requests.get("https://api.anthropic.com", timeout=10)
        print(f"[Claude] Connectivity OK — HTTP {probe.status_code}")
    except Exception as e:
        print(f"[Claude] Connectivity FAILED ({type(e).__name__}): {e}")
        traceback.print_exc()

    client  = Anthropic(api_key=ANTHROPIC_API_KEY)
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    all_results = []
    credits_exhausted = False

    print(f"[Claude] Sending {len(items)} items in {len(batches)} batches of up to {BATCH_SIZE}...")

    for idx, batch in enumerate(batches, 1):
        if credits_exhausted:
            print(f"[Claude] Batch {idx} skipped — credits exhausted")
            continue
        print(f"[Claude] Batch {idx}/{len(batches)} ({len(batch)} items)...")
        last_exc = None
        for attempt in range(1, 4):  # up to 3 attempts
            try:
                response = client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": build_user_message(batch)}],
                )
                parsed = _parse_claude_response(response.content[0].text)
                if parsed:
                    all_results.extend(parsed)
                else:
                    print(f"[Claude] Batch {idx}: could not parse response")
                    print(response.content[0].text[:300])
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if "credit balance is too low" in str(e):
                    credits_exhausted = True
                    print(f"[Claude] Batch {idx}: credits exhausted — stopping batches")
                    break
                print(f"[Claude] Batch {idx} attempt {attempt}/3 error ({type(e).__name__}): {e}")
                traceback.print_exc()
                if attempt < 3:
                    # Use longer backoff for overload (529) vs other errors
                    delay = 60 * attempt if "overloaded" in str(e).lower() else 5 * attempt
                    print(f"[Claude] Waiting {delay}s before retry...")
                    time.sleep(delay)
        if last_exc is not None and not credits_exhausted:
            print(f"[Claude] Batch {idx} failed all 3 attempts — skipping")

    print(f"[Claude] {len(all_results)} situations analyzed across all batches")
    return all_results, credits_exhausted


def filter_by_relevance(situations, min_score=6):
    filtered = [s for s in situations if int(s.get("relevance_score", 0)) >= min_score]
    dropped  = len(situations) - len(filtered)
    print(f"[Filter] {len(situations)} -> {len(filtered)} situations (dropped {dropped} below score {min_score})")
    return filtered


# ── Seen-item tracking ────────────────────────────────────────────────────────

def get_item_id(situation):
    raw = situation.get("source_url") or situation.get("headline") or str(situation)
    return hashlib.md5(raw.encode()).hexdigest()

def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_PATH, "w") as f:
        json.dump(list(seen), f)

def filter_new(situations, seen):
    new = [s for s in situations if get_item_id(s) not in seen]
    print(f"[Seen] {len(situations)} situations, {len(new)} new (dropped {len(situations) - len(new)} already seen)")
    return new


# ── Output ────────────────────────────────────────────────────────────────────

def save_feed(situations, new_count):
    output = {
        "date":          TODAY,
        "run_timestamp": datetime.utcnow().isoformat() + "Z",
        "count":         len(situations),
        "new_count":     new_count,
        "situations":    situations,
    }
    os.makedirs(os.path.dirname(FEED_PATH), exist_ok=True)
    with open(FEED_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Feed] Saved {len(situations)} situations ({new_count} new) to {FEED_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Special Situations Feed — {TODAY} ===")

    all_items = (
        fetch_edgar()
        + fetch_news()
        + fetch_prnewswire()
        + fetch_globenewswire()
        + fetch_courtlistener()
        + fetch_seekingalpha()
    )

    deduped     = deduplicate(all_items)
    prefiltered = keyword_prefilter(deduped)
    analyzed, credits_exhausted = analyze_with_claude(prefiltered)
    situations  = filter_by_relevance(analyzed, min_score=5)

    if credits_exhausted:
        send_credit_alert()

    seen     = load_seen()
    new_only = filter_new(situations, seen)
    save_feed(situations, new_count=len(new_only))

    # Mark all of today's situations as seen for future runs
    seen.update(get_item_id(s) for s in situations)
    save_seen(seen)

    print("=== Done ===")


if __name__ == "__main__":
    main()
