#!/usr/bin/env python3
"""
scraper_gha.py — Headless Google Flights scraper for GitHub Actions
Runs twice daily on GitHub's servers (9am + 8pm Vietnam time).
Sends email notifications based on notification_config.json settings.
"""

import json, os, re, smtplib, time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────

MAX_PRICE = 600
MAX_STOPS = 2

PREFERRED_DATES  = [date(2026, 8, d) for d in range(18, 32)]
ACCEPTABLE_DATES = [date(2026, 9, d) for d in range(1, 4)]
ALL_DATES        = PREFERRED_DATES + ACCEPTABLE_DATES

BANNED = {
    "LHR","LGW","LCY","STN","LTN",
    "DXB","DWC","AUH","DOH","KWI",
    "BAH","MCT","RUH","JED","DMM",
    "AMM","BEY","TLV","BGW","BSR",
    "THR","IKA","KBL","SHJ",
}

BASE_DIR = Path(__file__).parent
OUTPUT   = BASE_DIR / "flights_data.json"
NOTIF_CFG = BASE_DIR / "notification_config.json"

HUB_REGION = {
    **{k: "SE Asia"  for k in ["SIN","BKK","DMK","KUL","MNL"]},
    **{k: "China"    for k in ["PEK","PKX","PVG","SHA","CAN","SZX","CTU","XIY","CKG"]},
    **{k: "Korea"    for k in ["ICN","GMP"]},
    **{k: "Japan"    for k in ["NRT","HND","KIX"]},
    **{k: "Europe"   for k in ["FRA","CDG","MUC","ZRH","BRU","VIE","IST"]},
    "HKG": "Hong Kong", "TPE": "Taiwan",
}

# ─────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────

def load_notif_cfg() -> dict:
    if NOTIF_CFG.exists():
        return json.loads(NOTIF_CFG.read_text())
    return {"email": "", "notify_on_run": False, "notify_on_deal": False,
            "deal_threshold_eur": 400}

def hub_badge(code: str) -> str:
    region = HUB_REGION.get(code, "")
    colours = {
        "SE Asia":    ("#065f46", "#d1fae5"),
        "China":      ("#991b1b", "#fee2e2"),
        "Korea":      ("#166534", "#dcfce7"),
        "Japan":      ("#1e3a5f", "#dbeafe"),
        "Europe":     ("#92400e", "#fef3c7"),
        "Hong Kong":  ("#4b5563", "#f3f4f6"),
        "Taiwan":     ("#6b21a8", "#f3e8ff"),
    }
    fg, bg = colours.get(region, ("#374151", "#f3f4f6"))
    return (f'<span style="background:{bg};color:{fg};padding:2px 7px;'
            f'border-radius:4px;font-size:12px;font-weight:600;">{code}</span>')

def flight_row_html(f: dict, rank: int) -> str:
    layover_html = " → ".join(hub_badge(l) for l in (f.get("layovers") or []))
    stops = f.get("stops")
    stops_str = ("nonstop" if stops == 0 else f"{stops} stop{'s' if stops != 1 else ''}"
                 if stops is not None else "?")
    return f"""
    <tr style="background:{'#f0fdf4' if rank == 1 else '#ffffff'}">
      <td style="padding:10px 12px;font-weight:700;color:{'#ca8a04' if rank==1 else '#6b7280'}">{rank}</td>
      <td style="padding:10px 12px;font-weight:600">{f.get('airline','—')}</td>
      <td style="padding:10px 12px;color:#374151">{f.get('departs','—')} → {f.get('arrives','—')}</td>
      <td style="padding:10px 12px">{layover_html or '<span style="color:#9ca3af">direct</span>'}</td>
      <td style="padding:10px 12px;color:#6b7280;font-size:13px">{f.get('duration','—')} · {stops_str}</td>
      <td style="padding:10px 12px;font-size:1.1rem;font-weight:800;color:#2563eb">€{f['price_eur']:.0f}</td>
    </tr>"""

def build_run_email(flights_by_date: dict, cfg: dict) -> tuple[str, str]:
    all_flights = [(d, f) for d, fl in flights_by_date.items() for f in fl]
    total       = len(all_flights)
    best        = min(all_flights, key=lambda x: x[1]["price_eur"]) if all_flights else None

    subject = f"✈ HAN→AMS Daily Update — {'Best: €'+str(int(best[1]['price_eur']))+' on '+best[0] if best else 'No deals found'}"

    rows = ""
    for d, flights in sorted(flights_by_date.items()):
        if not flights:
            continue
        pref = d <= "2026-08-31"
        label = "★ Preferred" if pref else "◆ Acceptable"
        colour = "#16a34a" if pref else "#d97706"
        rows += f"""
        <tr><td colspan="6" style="padding:14px 12px 6px;font-weight:700;
            color:{colour};border-top:2px solid #e5e7eb;font-size:14px">
          {d} &nbsp; <span style="font-weight:400;font-size:12px">{label}</span>
        </td></tr>"""
        for i, f in enumerate(flights[:5], 1):
            rows += flight_row_html(f, i)

    html = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f9fafb;margin:0;padding:20px;">
    <div style="max-width:700px;margin:0 auto;background:#fff;border-radius:12px;
        overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08);">

      <div style="background:linear-gradient(135deg,#0f2d5c,#2563eb);color:#fff;padding:24px 28px;">
        <h1 style="margin:0;font-size:1.3rem">✈ HAN → AMS Flight Tracker</h1>
        <p style="margin:6px 0 0;opacity:.85;font-size:.9rem">
          Daily run complete · {total} flight(s) found under €{cfg.get('deal_threshold_eur',500)}
        </p>
      </div>

      {f'''<div style="background:#dcfce7;padding:14px 28px;border-bottom:1px solid #bbf7d0">
        <strong style="color:#166534">🏆 Best deal today:</strong>
        <span style="color:#166534"> €{int(best[1]["price_eur"])} — {best[1].get("airline","?")}
          on {best[0]} via {", ".join(best[1].get("layovers") or ["—"])}</span>
      </div>''' if best else ''}

      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="background:#1e3a5f;color:#fff">
          <th style="padding:10px 12px;text-align:left">#</th>
          <th style="padding:10px 12px;text-align:left">Airline</th>
          <th style="padding:10px 12px;text-align:left">Times</th>
          <th style="padding:10px 12px;text-align:left">Via</th>
          <th style="padding:10px 12px;text-align:left">Duration · Stops</th>
          <th style="padding:10px 12px;text-align:left">Price</th>
        </tr></thead>
        <tbody>{rows if rows else '<tr><td colspan="6" style="padding:20px;text-align:center;color:#9ca3af">No flights found under €'+str(MAX_PRICE)+' this run.</td></tr>'}</tbody>
      </table>

      <div style="padding:18px 28px;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb">
        Avoiding Middle East + London layovers · Max 2 stops · Next check in ~11h
        · <a href="https://github.com" style="color:#2563eb">View on GitHub</a>
      </div>
    </div>
    </body></html>"""
    return subject, html

def build_deal_email(date_str: str, flights: list[dict], threshold: float) -> tuple[str, str]:
    best = flights[0]
    subject = f"🚨 Deal Alert! €{int(best['price_eur'])} HAN→AMS on {date_str} — {best.get('airline','?')}"
    rows = "".join(flight_row_html(f, i) for i, f in enumerate(flights[:5], 1))
    html = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f9fafb;margin:0;padding:20px;">
    <div style="max-width:700px;margin:0 auto;background:#fff;border-radius:12px;
        overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08);">
      <div style="background:linear-gradient(135deg,#166534,#16a34a);color:#fff;padding:24px 28px;">
        <h1 style="margin:0;font-size:1.3rem">🚨 Deal Alert — HAN → AMS</h1>
        <p style="margin:6px 0 0;opacity:.9;font-size:.9rem">
          Flight(s) found under €{int(threshold)} on {date_str}
        </p>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="background:#1e3a5f;color:#fff">
          <th style="padding:10px 12px;text-align:left">#</th>
          <th style="padding:10px 12px;text-align:left">Airline</th>
          <th style="padding:10px 12px;text-align:left">Times</th>
          <th style="padding:10px 12px;text-align:left">Via</th>
          <th style="padding:10px 12px;text-align:left">Duration · Stops</th>
          <th style="padding:10px 12px;text-align:left">Price</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="padding:18px 28px;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb">
        Book soon — these fares disappear fast. Avoiding ME + London layovers.
      </div>
    </div></body></html>"""
    return subject, html

def send_email(to: str, subject: str, html: str):
    user     = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        print("  ⚠  Email skipped — GMAIL_USER / GMAIL_APP_PASSWORD secrets not set")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Flight Tracker <{user}>"
    msg["To"]      = to
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(user, password)
            smtp.sendmail(user, to, msg.as_string())
        print(f"  ✉  Email sent → {to}")
    except Exception as e:
        print(f"  ✗  Email failed: {e}")

# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def parse_stops(text: str) -> int:
    t = text.lower()
    if "nonstop" in t or "direct" in t:
        return 0
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else 1

def layovers_from_text(text: str) -> list[str]:
    codes = re.findall(r"\b([A-Z]{3})\b", text)
    return [c for c in codes if c not in {"EUR","USD","GBP","HAN","AMS","EST","GMT"}]

def is_allowed(price: float, stops: int | None, layovers: list[str]) -> bool:
    if price >= MAX_PRICE:
        return False
    if stops is not None and stops > MAX_STOPS:
        return False
    return not any(l in BANNED for l in layovers)

# ─────────────────────────────────────────────────────────
# Scraper
# ─────────────────────────────────────────────────────────

def make_url(dep: date) -> str:
    return (f"https://www.google.com/travel/flights/search"
            f"?q=Flights+from+Hanoi+to+Amsterdam+on+{dep}&hl=en&curr=EUR")

def scrape_date(page, dep: date) -> list[dict]:
    try:
        page.goto(make_url(dep), wait_until="domcontentloaded", timeout=30_000)
    except PWTimeout:
        print("    timed out")
        return []

    # Dismiss consent dialogs
    for sel in ['button[aria-label*="Accept"]', 'button:has-text("Accept all")',
                'button:has-text("I agree")', 'button[aria-label*="agree"]']:
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=2000):
                b.click(); page.wait_for_timeout(800); break
        except Exception:
            pass

    # Wait for results
    for sel in ['[data-resultid]', '[jsname="IWWDBc"]',
                '.gws-flights-results__result-item']:
        try:
            page.wait_for_selector(sel, timeout=15_000); break
        except PWTimeout:
            continue
    else:
        page.wait_for_timeout(5000)

    flights = []
    cards = page.locator('[data-resultid]').all() or page.locator('[jsname="IWWDBc"]').all()

    for card in cards:
        try:
            text = card.inner_text()
            m = re.search(r"€\s*([\d,]+)", text)
            if not m:
                continue
            price = float(m.group(1).replace(",", ""))
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            airline = lines[0] if lines else "Unknown"
            stop_line = next((l for l in lines if "stop" in l.lower() or "nonstop" in l.lower()), "")
            stops    = parse_stops(stop_line)
            layovers = layovers_from_text(stop_line)
            dur_m = re.search(r"(\d+)\s*hr?\s*(\d+)?\s*min?", text, re.I)
            duration = f"{dur_m.group(1)}h {dur_m.group(2) or '0'}m" if dur_m else None
            times = re.findall(r"\b(\d{1,2}:\d{2})\b", text)
            departs = f"{times[0]} HAN" if times else None
            arrives = f"{times[1]} AMS" if len(times) > 1 else None
            if not is_allowed(price, stops, layovers):
                continue
            flights.append({"price_eur": price, "airline": airline, "stops": stops,
                            "layovers": layovers, "duration": duration,
                            "departs": departs, "arrives": arrives,
                            "source": "google-flights"})
        except Exception:
            continue

    # Regex fallback
    if not flights:
        full = page.inner_text("body")
        seen: set[float] = set()
        for m in re.finditer(r"€\s*([\d,]+)", full):
            try:
                p = float(m.group(1).replace(",", ""))
                if 50 < p < MAX_PRICE and p not in seen:
                    seen.add(p)
                    flights.append({"price_eur": p, "airline": "Unknown",
                                    "stops": None, "layovers": [], "duration": None,
                                    "departs": None, "arrives": None,
                                    "source": "google-flights"})
            except ValueError:
                pass

    top = sorted(flights, key=lambda x: x["price_eur"])[:10]
    if top:
        print(f"    ✓ {len(top)} flight(s): " + ", ".join(f"€{f['price_eur']:.0f}" for f in top))
    else:
        print("    – no results")
    return top

# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────

def run():
    print("=" * 58)
    print("  HAN → AMS Scraper  |  < €500  |  Max 2 stops")
    print("=" * 58)

    cfg = load_notif_cfg()
    flights_by_date: dict[str, list[dict]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="en-GB", timezone_id="Asia/Ho_Chi_Minh",
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        for dep in ALL_DATES:
            label = "★" if dep in PREFERRED_DATES else " "
            print(f"\n{label} {dep}")
            flights_by_date[dep.isoformat()] = scrape_date(page, dep)
            time.sleep(3)

        browser.close()

    # Save results
    output = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Live data — scraped by GitHub Actions",
        "config": {
            "origin": "HAN", "destination": "AMS",
            "max_price_eur": MAX_PRICE, "max_stops": MAX_STOPS,
            "preferred_dates":  [d.isoformat() for d in PREFERRED_DATES],
            "acceptable_dates": [d.isoformat() for d in ACCEPTABLE_DATES],
            "banned_airports": sorted(BANNED),
        },
        "flights_by_date": flights_by_date,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    all_flights = [(d, f) for d, fl in flights_by_date.items() for f in fl]
    print(f"\n{'='*58}")
    print(f"  {len(all_flights)} total flights across all dates.")
    if all_flights:
        best_date, best = min(all_flights, key=lambda x: x[1]["price_eur"])
        print(f"  Best: €{best['price_eur']:.0f} ({best['airline']}) on {best_date}")

    # ── Notifications ────────────────────────────────────
    to_email  = cfg.get("email", "")
    threshold = float(cfg.get("deal_threshold_eur", 400))

    if to_email:
        # Deal alerts — send per date if any flight is under threshold
        if cfg.get("notify_on_deal"):
            for d, flights in flights_by_date.items():
                deals = [f for f in flights if f["price_eur"] < threshold]
                if deals:
                    print(f"\n  🚨 Deal alert: {len(deals)} flight(s) under €{threshold:.0f} on {d}")
                    subj, html = build_deal_email(d, deals, threshold)
                    send_email(to_email, subj, html)

        # Daily run summary
        if cfg.get("notify_on_run"):
            print(f"\n  ✉  Sending daily summary to {to_email}…")
            subj, html = build_run_email(flights_by_date, cfg)
            send_email(to_email, subj, html)
    else:
        print("\n  (Email not configured in notification_config.json)")

    print("=" * 58)

if __name__ == "__main__":
    run()
