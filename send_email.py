import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from quotes import get_daily_quote

load_dotenv()

GMAIL_USER     = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = "".join(c for c in (os.getenv("GMAIL_APP_PASSWORD") or "") if c.isascii()).replace(" ", "")
RECIPIENT      = os.getenv("RECIPIENT_EMAIL")
FEED_PATH      = os.path.join(os.path.dirname(__file__), "feed_data", "feed.json")

CATEGORY_LABELS = {
    "ma":          ("M&A",         "#3b82f6"),
    "spin":        ("Spin-off",    "#a855f7"),
    "distress":    ("Distress",    "#ef4444"),
    "activist":    ("Activist",    "#22c55e"),
    "cvr":         ("CVR",         "#f59e0b"),
    "dissolution": ("Dissolution", "#94a3b8"),
}

SIGNAL_COLORS = {
    "high": ("#7f1d1d", "#fca5a5"),
    "med":  ("#78350f", "#fcd34d"),
    "low":  ("#14532d", "#86efac"),
}


def load_feed():
    with open(FEED_PATH) as f:
        return json.load(f)


def fmt_date(iso_date):
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %-d")
    except Exception:
        return iso_date


def signal_badge(signal):
    s = (signal or "").lower()
    bg, fg = SIGNAL_COLORS.get(s, ("#1e293b", "#94a3b8"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:12px;'
        f'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">'
        f'{s}</span>'
    )


def category_section(label, color, situations):
    rows = ""
    for s in situations:
        ticker     = s.get("ticker") or "—"
        company    = s.get("company") or ""
        headline   = s.get("headline") or ""
        thesis     = s.get("thesis") or ""
        signal     = s.get("signal") or ""
        source_url = s.get("source_url") or ""

        view_source = (
            f'<a href="{source_url}" style="font-size:11px;color:#6366f1;text-decoration:none;">'
            f'View source ↗</a>'
            if source_url else ""
        )

        rows += f"""
        <tr>
          <td style="padding:16px 20px;border-bottom:1px solid #1e293b;vertical-align:top;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-bottom:8px;">
                  <span style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;
                    color:#a5b4fc;background:#1e2235;border:1px solid #2d3148;
                    padding:2px 8px;border-radius:4px;">{ticker}</span>
                  <span style="font-size:13px;color:#94a3b8;margin-left:8px;">{company}</span>
                  <span style="float:right;">{signal_badge(signal)}</span>
                </td>
              </tr>
              <tr>
                <td style="font-size:14px;font-weight:600;color:#e2e8f0;padding-bottom:6px;
                  line-height:1.4;">{headline}</td>
              </tr>
              <tr>
                <td style="font-size:13px;color:#94a3b8;line-height:1.6;padding-bottom:8px;">{thesis}</td>
              </tr>
              <tr>
                <td>{view_source}</td>
              </tr>
            </table>
          </td>
        </tr>"""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
      style="margin-bottom:24px;border:1px solid #2d3148;border-radius:8px;overflow:hidden;">
      <tr>
        <td style="background:#1a1d27;padding:10px 20px;border-bottom:2px solid {color};">
          <span style="font-size:11px;font-weight:700;text-transform:uppercase;
            letter-spacing:0.08em;color:{color};">{label}</span>
          <span style="font-size:11px;color:#475569;margin-left:8px;">{len(situations)} situation{'s' if len(situations) != 1 else ''}</span>
        </td>
      </tr>
      {rows}
    </table>"""


def build_html(feed):
    date_str   = fmt_date(feed.get("date", ""))
    count      = feed.get("count", 0)
    timestamp  = feed.get("run_timestamp", "")
    situations = feed.get("situations", [])

    try:
        ts_fmt = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%-I:%M %p UTC")
    except Exception:
        ts_fmt = timestamp

    # Group by category
    grouped = {}
    for s in situations:
        t = (s.get("type") or "").lower()
        grouped.setdefault(t, []).append(s)

    sections = ""
    for key in ["ma", "spin", "distress", "activist", "cvr", "dissolution"]:
        items = grouped.get(key, [])
        if not items:
            continue
        label, color = CATEGORY_LABELS.get(key, (key.upper(), "#64748b"))
        sections += category_section(label, color, items)

    quote, _ = get_daily_quote()
    subject = f"Special Situations · {date_str} · {count} signal{'s' if count != 1 else ''}"

    quote_block = f"""
          <!-- Quote -->
          <tr>
            <td style="background:#13151f;border:1px solid #2d3148;border-top:none;
              padding:24px 32px;text-align:center;">
              <div style="width:32px;height:1px;background:#3d4168;margin:0 auto 20px;"></div>
              <p style="font-family:Georgia,'Times New Roman',serif;font-style:italic;
                font-size:15px;line-height:1.7;color:#c4c9e2;margin:0 0 12px;
                letter-spacing:0.01em;">&ldquo;{quote}&rdquo;</p>
              <p style="font-family:Georgia,'Times New Roman',serif;font-size:12px;
                color:#4f5680;margin:0;letter-spacing:0.08em;text-transform:uppercase;">
                &mdash; Thomas Jefferson</p>
              <div style="width:32px;height:1px;background:#3d4168;margin:20px auto 0;"></div>
              <p style="font-family:Georgia,'Times New Roman',serif;font-style:italic;
                font-size:13px;color:#7c83a8;margin:12px 0 0;">Love you Dad, hope you have a great day! &mdash; Paige</p>
            </td>
          </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;">

          <!-- Header -->
          <tr>
            <td style="background:#1a1d27;border:1px solid #2d3148;border-radius:10px 10px 0 0;
              padding:20px 24px;border-bottom:none;">
              <span style="font-size:11px;font-weight:700;text-transform:uppercase;
                letter-spacing:0.1em;color:#a5b4fc;">Special Situations Feed</span>
              <span style="float:right;font-size:11px;color:#475569;">{ts_fmt}</span>
              <div style="font-size:22px;font-weight:700;color:#e2e8f0;margin-top:6px;">{date_str}</div>
              <div style="font-size:13px;color:#64748b;margin-top:2px;">{count} situations identified across SEC filings</div>
            </td>
          </tr>

          {quote_block}

          <!-- Body -->
          <tr>
            <td style="background:#0f1117;padding:24px 0;">
              {sections}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="border-top:1px solid #1e293b;padding:16px 0;text-align:center;">
              <span style="font-size:11px;color:#334155;">
                Generated by Special Situations Feed · Source: SEC EDGAR
              </span>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, html


def send_email(subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT, msg.as_string())


def main():
    print(f"[Email] Loading feed from {FEED_PATH}...")
    feed = load_feed()

    subject, html = build_html(feed)
    print(f"[Email] Subject: {subject}")
    print(f"[Email] Sending to {RECIPIENT}...")

    send_email(subject, html)
    print("[Email] Sent successfully.")


if __name__ == "__main__":
    main()
