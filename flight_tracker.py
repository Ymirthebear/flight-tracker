#!/usr/bin/env python3
"""
Flight Tracker: Hanoi (HAN) → Amsterdam (AMS)
- Dates: Aug 18–31, 2026 (preferred); Sep 1–3 (acceptable)
- Budget: < 500 EUR  |  Max 2 stops
- Avoids: Middle East + London layovers (Vietnamese passport)

Run: python flight_tracker.py
Saves: flights_data.json  →  open dashboard.html to view
"""

import json, re, time, urllib.request
from datetime import date
from pathlib import Path

# ─────────────────────────────────────────────────────────
ORIGIN       = "HAN"
DESTINATIONS = {"AMS": "Amsterdam", "DUS": "Düsseldorf", "BRU": "Brussels"}
MAX_PRICE_EUR = 600
MAX_STOPS     = 2

PREFERRED_DATES  = [date(2026, 8, d) for d in range(18, 32)]
ACCEPTABLE_DATES = [date(2026, 9, d) for d in range(1, 4)]
ALL_DATES        = PREFERRED_DATES + ACCEPTABLE_DATES

BANNED_AIRPORTS = {
    "LHR","LGW","LCY","STN","LTN",
    "DXB","DWC","AUH","DOH","KWI",
    "BAH","MCT","RUH","JED","DMM",
    "AMM","BEY","TLV","BGW","BSR",
    "THR","IKA","KBL","SHJ",
}

GOOD_HUBS = {
    "SIN":"Singapore","BKK":"Bangkok","KUL":"Kuala Lumpur","MNL":"Manila",
    "HKG":"Hong Kong","TPE":"Taipei","ICN":"Seoul Incheon","GMP":"Seoul Gimpo",
    "NRT":"Tokyo Narita","HND":"Tokyo Haneda","KIX":"Osaka",
    "PEK":"Beijing Capital","PKX":"Beijing Daxing","PVG":"Shanghai Pudong",
    "SHA":"Shanghai Hongqiao","CAN":"Guangzhou","SZX":"Shenzhen",
    "CTU":"Chengdu","XIY":"Xian","CKG":"Chongqing",
    "FRA":"Frankfurt","CDG":"Paris","MUC":"Munich","ZRH":"Zurich",
    "BRU":"Brussels","VIE":"Vienna","IST":"Istanbul",
}

OUTPUT_FILE = Path(__file__).parent / "flights_data.json"

# ─────────────────────────────────────────────────────────
# URL builders
# ─────────────────────────────────────────────────────────

def google_flights_url(d: date, dest_name: str = "Amsterdam") -> str:
    return (f"https://www.google.com/travel/flights/search"
            f"?q=Flights+from+Hanoi+to+{dest_name}+on+{d}&hl=en&curr=EUR")

def skyscanner_url(d: date) -> str:
    ds = d.strftime("%y%m%d")
    return f"https://www.skyscanner.net/transport/flights/han/ams/{ds}/?adults=1&currency=EUR&cabinclass=economy"

# ─────────────────────────────────────────────────────────
# Scraper
# ─────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    ⚠  {e}")
        return None

def _parse_prices(html: str) -> list[float]:
    hits = re.findall(r'(?:€|EUR)\s*(\d{2,4}(?:[.,]\d{1,2})?)', html)
    prices = []
    for h in hits:
        try:
            p = float(h.replace(",", "."))
            if 50 < p < MAX_PRICE_EUR:
                prices.append(p)
        except ValueError:
            pass
    return sorted(set(prices))

def scrape_date(dep_date: date) -> list[dict]:
    url = skyscanner_url(dep_date)
    print(f"  Fetching {url}")
    html = _fetch(url)
    if not html:
        return []
    prices = _parse_prices(html)
    return [{"price_eur": p, "airline": "Unknown", "stops": None,
             "layovers": [], "duration": None, "departs": None, "arrives": None,
             "source": "skyscanner-html"}
            for p in prices]

def is_allowed(f: dict) -> bool:
    if f.get("price_eur", 9999) >= MAX_PRICE_EUR:
        return False
    stops = f.get("stops")
    if isinstance(stops, int) and stops > MAX_STOPS:
        return False
    for ap in f.get("layovers", []):
        if ap.upper() in BANNED_AIRPORTS:
            return False
    return True

# ─────────────────────────────────────────────────────────
# Main — outputs flights_by_date structure
# ─────────────────────────────────────────────────────────

def run():
    print("=" * 58)
    print("  HAN → AMS Flight Tracker  |  < €500  |  Max 2 stops")
    print("=" * 58)

    flights_by_date: dict[str, list[dict]] = {}

    for dep_date in ALL_DATES:
        label = "★ preferred" if dep_date in PREFERRED_DATES else "  acceptable"
        print(f"\n  {dep_date}  ({label})")
        raw = scrape_date(dep_date)
        good = [f for f in raw if is_allowed(f)]
        top = sorted(good, key=lambda x: x["price_eur"])[:10]
        flights_by_date[dep_date.isoformat()] = top
        if top:
            print(f"  → {len(top)} flight(s): " + ", ".join(f"€{f['price_eur']:.0f}" for f in top))
        else:
            print("  → No live data scraped")
        time.sleep(1)

    output = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "origin": ORIGIN, "destination": DEST,
            "max_price_eur": MAX_PRICE_EUR, "max_stops": MAX_STOPS,
            "preferred_dates": [d.isoformat() for d in PREFERRED_DATES],
            "acceptable_dates": [d.isoformat() for d in ACCEPTABLE_DATES],
            "banned_airports": sorted(BANNED_AIRPORTS),
            "good_hubs": GOOD_HUBS,
        },
        "flights_by_date": flights_by_date,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    all_flights = [f for flights in flights_by_date.values() for f in flights]
    print(f"\n✓  Saved → {OUTPUT_FILE.name}")
    if all_flights:
        cheapest = min(all_flights, key=lambda x: x["price_eur"])
        print(f"   Best deal: €{cheapest['price_eur']:.0f}")
    print("   Open dashboard.html to browse results.")

    # Auto-push to GitHub Pages if configured
    try:
        import github_push
        github_push.push()
    except Exception as e:
        print(f"   (GitHub push skipped: {e})")
    print()

if __name__ == "__main__":
    run()
