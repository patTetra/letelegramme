#!/usr/bin/env python3
"""
Scan quotidien des nouveautés tech grand public.

Va chercher les derniers articles/produits sur une liste de flux RSS
(sites tech) et de flux Kickstarter par catégorie, applique un filtrage
simple par mots-clés et budget, puis met à jour nouveautes.json à la
racine du repo (lu ensuite par index.html et par Home Assistant).
"""

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import feedparser

# ---------------------------------------------------------------------------
# CONFIGURATION — à adapter librement
# ---------------------------------------------------------------------------

# Flux RSS de sites tech grand public.
# ⚠️ À vérifier/ajuster : les URLs de flux changent parfois. Pour trouver le
# flux d'un site, cherche un lien "RSS" en pied de page, ou essaie
# <site>/feed/ ou <site>/rss.
RSS_FEEDS = [
    "https://www.frandroid.com/feed",
    "https://www.numerama.com/feed/",
    "https://www.01net.com/feed/",
    "https://www.lesnumeriques.com/rss.xml",
    "https://www.theverge.com/rss/index.xml",
]

# Flux Kickstarter par catégorie (ceux-ci sont stables et officiels).
# Catégorie "technology" = 16, sous-catégorie "gadgets" = 335, etc.
# Liste complète des IDs : https://www.kickstarter.com/categories
KICKSTARTER_FEEDS = [
    "https://www.kickstarter.com/discover/categories/technology.rss",
    "https://www.kickstarter.com/discover/categories/technology/gadgets.rss",
]

# Indiegogo n'a pas de flux RSS officiel simple à ce jour : la catégorie
# tech doit être surveillée manuellement pour l'instant, ou via un flux
# tiers si tu en trouves un fiable. Champ laissé vide volontairement.
INDIEGOGO_FEEDS: list[str] = []

# Mots-clés qui doivent apparaître (titre ou résumé) pour qu'un item soit
# retenu comme candidat "test produit accessible au grand public".
# Reste volontairement large ; affine avec le temps selon ce qui remonte.
KEYWORDS = [
    "connecté", "connectée", "connectés", "objet connecté",
    "télescope", "domotique", "gadget", "test", "accessible",
    "smart home", "wearable", "montre connectée", "caméra",
    "robot", "drone", "vélo électrique", "trottinette",
]

# Budget max en euros pour qu'un produit soit jugé "grand public accessible".
# Un item sans prix détecté n'est pas exclu, juste marqué price=null.
BUDGET_MAX = 1000

OUTPUT_FILE = Path(__file__).parent / "nouveautes.json"
MAX_HISTORY_DAYS = 60  # purge des entrées plus anciennes que ça


# ---------------------------------------------------------------------------
# LOGIQUE
# ---------------------------------------------------------------------------

def extract_price(text: str) -> float | None:
    """Cherche un montant en euros dans un texte (ex: '349 €', '349€')."""
    match = re.search(r"(\d{2,5})\s*€", text)
    if match:
        return float(match.group(1))
    return None


def matches_keywords(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in KEYWORDS)


def make_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def fetch_feed_items(url: str, source_type: str) -> list[dict]:
    items = []
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] échec du parsing de {url}: {exc}")
        return items

    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        link = entry.get("link", "")
        if not title or not link:
            continue

        combined = f"{title} {summary}"
        if source_type == "rss" and not matches_keywords(combined):
            continue  # les flux Kickstarter sont déjà pré-filtrés par catégorie

        price = extract_price(combined)
        if price is not None and price > BUDGET_MAX:
            continue

        published = entry.get("published", "") or entry.get("updated", "")

        items.append({
            "id": make_id(link),
            "title": title,
            "link": link,
            "summary": summary[:400],
            "price": price,
            "source": source_type,
            "source_url": url,
            "published": published,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "status": "nouveau",  # nouveau | a_tester | archive
        })
    return items


def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return data.get("items", [])
    return []


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    by_id = {item["id"]: item for item in existing}
    for item in fresh:
        if item["id"] not in by_id:
            by_id[item["id"]] = item
        # si déjà connu, on garde le statut existant (nouveau/a_tester/archive)

    # purge des entrées trop anciennes pour ne pas faire grossir le fichier
    cutoff = datetime.now(timezone.utc).timestamp() - MAX_HISTORY_DAYS * 86400
    merged = []
    for item in by_id.values():
        try:
            detected = datetime.fromisoformat(item["detected_at"]).timestamp()
        except (KeyError, ValueError):
            detected = datetime.now(timezone.utc).timestamp()
        if detected >= cutoff or item.get("status") == "a_tester":
            merged.append(item)

    merged.sort(key=lambda x: x.get("detected_at", ""), reverse=True)
    return merged


def main() -> None:
    fresh: list[dict] = []

    for url in RSS_FEEDS:
        fresh.extend(fetch_feed_items(url, "rss"))

    for url in KICKSTARTER_FEEDS:
        fresh.extend(fetch_feed_items(url, "kickstarter"))

    for url in INDIEGOGO_FEEDS:
        fresh.extend(fetch_feed_items(url, "indiegogo"))

    existing = load_existing()
    merged = merge(existing, fresh)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": merged,
    }
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{len(fresh)} items scannés, {len(merged)} au total dans {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
