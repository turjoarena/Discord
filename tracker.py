import json
import os
import re
from urllib.parse import urljoin, urlparse
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

SKIP_TITLES = {
    "home", "login", "register", "signup", "dmca", "privacy", "terms",
    "contact", "about", "faq", "help", "requests", "updates", "launcher",
    "fighting", "classic", "anime", "adventure", "action", "trending",
    "top", "all games", "games", "genres", "categories", "popular",
    "new games", "free games", "simulation", "racing", "horror", "sports",
    "download now", "download", "recent updates", "view all", "see more",
    "read more", "more info", "play now"
}

BLOCKED_PATH_PARTS = {
    "login", "register", "signup", "dmca", "privacy", "terms",
    "contact", "about", "faq", "category", "categories", "genre",
    "genres", "tag", "tags", "search", "page", "requests", "updates",
    "launcher", "discord", "telegram", "youtube"
}


def load_seen_games() -> list[str]:
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


def save_seen_games(seen: list[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-400:], f, indent=2, ensure_ascii=False)


def title_from_slug(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return ""
    slug = re.sub(r"[-_]+", " ", parts[-1]).strip()
    return slug.title() if len(slug) >= 2 else ""


def clean_game_entry(url: str, raw_title: str) -> dict | None:
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()

    if not path or "#" in url or parsed.netloc.lower() != urlparse(TARGET_URL).netloc.lower():
        return None

    parts = path.split("/")
    if any(part in BLOCKED_PATH_PARTS for part in parts):
        return None

    title = " ".join(raw_title.split()).strip()
    lower_title = title.lower()

    if lower_title in SKIP_TITLES or len(title) < 2:
        if any(word in lower_title for word in ("download", "recent updates", "view all", "see more")):
            slug_title = title_from_slug(url)
            if slug_title and slug_title.lower() not in SKIP_TITLES:
                title = slug_title
            else:
                return None
        else:
            return None

    if len(parts) == 1 and "-" not in parts[0] and len(title.split()) == 1:
        return None

    return {
        "title": title[:200],
        "url": url,
    }


def scrape_latest_games() -> list[dict]:
    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=25)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    games = []
    seen_urls = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue

        full_url = urljoin(TARGET_URL, href)
        if full_url in seen_urls:
            continue

        entry = clean_game_entry(full_url, anchor.get_text(" ", strip=True))
        if not entry:
            continue

        seen_urls.add(full_url)
        games.append(entry)

        if len(games) >= 15:
            break

    return games


def fetch_game_details(game_url: str, fallback_title: str) -> dict:
    details = {
        "title": fallback_title,
        "version": "N/A",
        "release_date": "N/A",
        "genres": "N/A",
        "developer": "N/A",
        "overview": "Visit the game page for full details and download links.",
        "image_url": None,
    }

    try:
        resp = requests.get(game_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # পেজের মূল Heading থাকলে সেটি নেওয়া
        h1 = soup.find("h1")
        if h1:
            h1_text = " ".join(h1.get_text(" ", strip=True).split())
            if h1_text and len(h1_text) <= 180:
                details["title"] = h1_text

        # কভার/থাম্বনেইল ছবি খুঁজে বের করা
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            details["image_url"] = urljoin(game_url, og_img["content"].strip())
        else:
            for img in soup.find_all("img"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if not src or any(x in src.lower() for x in ("logo", "icon", "avatar", "svg")):
                    continue
                details["image_url"] = urljoin(game_url, src)
                break

        # পেজের লাইন/ব্লক থেকে Version, Release Date, Genres, Developer, Overview বের করা
        lines = [
            " ".join(el.get_text(" ", strip=True).split())
            for el in soup.find_all(["p", "li", "div", "tr", "span"])
            if len(" ".join(el.get_text(" ", strip=True).split())) < 600
        ]

        for i, line in enumerate(lines):
            low = line.lower()

            if details["version"] == "N/A" and "version" in low and len(line) < 80:
                m = re.search(r"(?:version|ver\.?|v)\s*[:\-]?\s*([A-Za-z0-9.\-_+]+)", line, re.I)
                if m:
                    details["version"] = m.group(1)
                elif i + 1 < len(lines) and len(lines[i + 1]) < 40:
                    details["version"] = lines[i + 1]

            if details["release_date"] == "N/A" and ("release date" in low or "released" in low) and len(line) < 100:
                parts = re.split(r"release date\s*[:\-]?|released\s*[:\-]?", line, flags=re.I)
                if len(parts) > 1 and parts[-1].strip():
                    details["release_date"] = parts[-1].strip()[:60]
                elif i + 1 < len(lines) and len(lines[i + 1]) < 50:
                    details["release_date"] = lines[i + 1][:60]

            if details["genres"] == "N/A" and ("genre" in low or "genres" in low) and len(line) < 150:
                parts = re.split(r"genres?\s*[:\-]?", line, flags=re.I)
                if len(parts) > 1 and parts[-1].strip():
                    details["genres"] = parts[-1].strip()[:120]
                elif i + 1 < len(lines) and len(lines[i + 1]) < 100:
                    details["genres"] = lines[i + 1][:120]

            if details["developer"] == "N/A" and ("developer" in low or "studio" in low) and len(line) < 120:
                parts = re.split(r"(?:developer|studio)\s*[:\-]?", line, flags=re.I)
                if len(parts) > 1 and parts[-1].strip():
                    details["developer"] = parts[-1].strip()[:100]
                elif i + 1 < len(lines) and len(lines[i + 1]) < 80:
                    details["developer"] = lines[i + 1][:100]

            if details["overview"] == "Visit the game page for full details and download links." and ("overview" in low or "about this game" in low or "description" in low):
                parts = re.split(r"(?:overview|about this game|description)\s*[:\-]?", line, flags=re.I)
                if len(parts) > 1 and len(parts[-1].strip()) > 25:
                    details["overview"] = parts[-1].strip()[:600]
                elif i + 1 < len(lines) and len(lines[i + 1]) > 25:
                    details["overview"] = lines[i + 1][:600]

    except Exception as exc:
        print(f"Details fetch warning for {game_url}: {exc}")

    return details


def send_discord_notification(game: dict) -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL environment variable পাওয়া যায়নি।")

    info = fetch_game_details(game["url"], game["title"])

    embed = {
        "title": f"🎮 {info['title']} has been added!",
        "url": game["url"],
        "description": "Experience the latest addition to our gaming library. Visit the game page to learn more.",
        "color": 0x7C3AED,  # পার্পল কালার (ছবির স্টাইলের সাথে মিলিয়ে)
        "fields": [
            {
                "name": "📦 Version",
                "value": info["version"],
                "inline": True,
            },
            {
                "name": "📅 Release Date",
                "value": info["release_date"],
                "inline": True,
            },
            {
                "name": "🏷️ Genres",
                "value": info["genres"],
                "inline": True,
            },
            {
                "name": "🛠️ Developer",
                "value": info["developer"],
                "inline": True,
            },
            {
                "name": "📝 Overview",
                "value": info["overview"][:1000],
                "inline": False,
            },
            {
                "name": "🔗 Links",
                "value": f"[Visit Game Page]({game['url']})",
                "inline": False,
            },
        ],
        "footer": {
            "text": "AnkerGames • New Game Alert",
        },
    }

    if info["image_url"]:
        embed["thumbnail"] = {"url": info["image_url"]}

    payload = {
        "content": "**New Game Added!**",
        "embeds": [embed],
    }

    r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()


def main() -> None:
    seen = load_seen_games()
    games = scrape_latest_games()

    if not games:
        print("কোনো গেমের লিংক পাওয়া যায়নি।")
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
