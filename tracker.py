import json
import os
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://ankergames.net/"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATE_FILE = "seen_games.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def load_seen_games() -> list[str]:
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


def save_seen_games(seen: list[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-200:], f, indent=2, ensure_ascii=False)


def scrape_latest_games() -> list[dict]:
    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=25)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    games = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        title = " ".join(anchor.get_text(" ", strip=True).split())

        if not title or len(title) < 2:
            continue

        full_url = urljoin(TARGET_URL, href)
        if not full_url.startswith(TARGET_URL):
            continue

        lower_url = full_url.lower()
        if any(skip in lower_url for skip in ["/login", "/register", "/dmca", "/privacy", "/terms", "#"]):
            continue

        games.append({
            "title": title[:200],
            "url": full_url,
        })

    unique_games = []
    seen_urls = set()
    for g in games:
        if g["url"] not in seen_urls:
            seen_urls.add(g["url"])
            unique_games.append(g)
        if len(unique_games) >= 15:
            break

    return unique_games


def send_discord_notification(game: dict) -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL environment variable পাওয়া যায়নি।")

    payload = {
        "content": "নতুন গেম আপডেট এসেছে!",
        "embeds": [
            {
                "title": game["title"],
                "url": game["url"],
                "description": "AnkerGames ওয়েবসাইটে নতুন গেম/আপডেট যুক্ত হয়েছে।",
                "color": 5814783,
            }
        ],
    }

    r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()


def main() -> None:
    seen = load_seen_games()
    games = scrape_latest_games()

    if not games:
        print("কোনো গেমের লিংক পাওয়া যায়নি। CSS selector বা Cloudflare চেক করুন।")
        return

    new_items = [g for g in reversed(games) if g["url"] not in seen]

    for game in new_items:
        send_discord_notification(game)
        seen.append(game["url"])
        print(f"Sent: {game['title']} -> {game['url']}")

    save_seen_games(seen)
    print(f"মোট নতুন গেম পাঠানো হয়েছে: {len(new_items)}")


if __name__ == "__main__":
    main()
