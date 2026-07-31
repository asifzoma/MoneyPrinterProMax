import re

from typing import List, Dict

import requests

from logstream import log

EN_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "MoneyPrinterProMax/1.0 (personal project; no contact)"

# Files matching these are almost always UI chrome/maintenance icons that
# appear on nearly every Wikipedia article, not illustrative photos.
_NOISE_PATTERNS = re.compile(
    r"(commons-logo|wiki_?letter|edit-clear|ambox|symbol_|folder_|"
    r"question_book|wikisource-logo|disambig|padlock|semi-protection|"
    r"wiktionary|ok_sign|crystal_clear|nuvola|flag_of_|ogv$|ogg$)",
    re.IGNORECASE,
)
_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png")

# Licenses permissive enough for commercial reuse (with attribution, which
# we always include). Anything containing "non-commercial"/"nc" or
# "no derivatives"/"nd" is rejected below regardless of this matching.
_PERMISSIVE_LICENSE = re.compile(
    r"(cc0|public domain|pd-|cc[\s-]*by(?![\s-]*nc)(?![\s-]*nd))", re.IGNORECASE
)
_RESTRICTIVE_LICENSE = re.compile(r"(non[\s-]?commercial|\bnc\b|no[\s-]?derivatives|\bnd\b)", re.IGNORECASE)


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _is_usable_license(extmetadata: dict) -> bool:
    license_name = (extmetadata.get("LicenseShortName", {}) or {}).get("value", "")
    if not license_name:
        # No machine-readable license (common for old/PD uploads) -- only
        # accept if explicitly marked non-copyrighted.
        copyrighted = (extmetadata.get("Copyrighted", {}) or {}).get("value", "")
        return copyrighted.lower() == "false"
    if _RESTRICTIVE_LICENSE.search(license_name):
        return False
    return bool(_PERMISSIVE_LICENSE.search(license_name))


def _is_photo_file(title: str) -> bool:
    lower = title.lower()
    if not lower.endswith(_PHOTO_EXTENSIONS):
        return False
    if _NOISE_PATTERNS.search(lower):
        return False
    return True


def _extract_images(pages: dict) -> List[Dict[str, str]]:
    results = []
    for page in pages.values():
        title = page.get("title", "")
        if not _is_photo_file(title):
            continue
        for info in page.get("imageinfo", []):
            extmetadata = info.get("extmetadata", {}) or {}
            if not _is_usable_license(extmetadata):
                continue
            # Prefer the direct original file over a thumbnail URL: Wikimedia's
            # on-the-fly thumbnail-generation service is far more aggressively
            # rate-limited than serving an original file directly (confirmed
            # empirically -- thumb URLs 429 much more readily under load).
            url = info.get("url") or info.get("thumburl")
            if not url:
                continue
            artist = _strip_html((extmetadata.get("Artist", {}) or {}).get("value", "Unknown"))
            license_name = (extmetadata.get("LicenseShortName", {}) or {}).get("value", "Public domain")
            results.append(
                {
                    "url": url,
                    "title": title,
                    "artist": artist or "Unknown",
                    "license": license_name,
                    "source_page": info.get("descriptionurl", ""),
                }
            )
    return results


def _images_from_wikipedia_article(title: str, count: int) -> List[Dict[str, str]]:
    """Try treating `title` as a Wikipedia article title directly -- the
    most topically-relevant source, since these are the literal images used
    to illustrate that exact subject."""
    try:
        resp = requests.get(
            EN_WIKIPEDIA_API,
            params={
                "action": "query",
                "generator": "images",
                "titles": title,
                "gimlimit": max(count * 3, 20),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as err:
        log(f"  [!] Wikipedia article image lookup failed for '{title}': {err}", "warning")
        return []

    pages = data.get("query", {}).get("pages", {})
    return _extract_images(pages)


def _images_from_commons_search(query: str, count: int) -> List[Dict[str, str]]:
    """Generic Commons keyword search, used when the query isn't itself a
    Wikipedia article (or that article had too few usable images)."""
    try:
        resp = requests.get(
            COMMONS_API,
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,  # File: namespace
                "gsrlimit": max(count * 3, 20),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as err:
        log(f"  [!] Commons search failed for '{query}': {err}", "warning")
        return []

    pages = data.get("query", {}).get("pages", {})
    return _extract_images(pages)


def search_for_commons_images(query: str, count: int) -> List[Dict[str, str]]:
    """Find usable, commercially-reusable images for `query`.

    Tries the query as a Wikipedia article title first (most relevant),
    then falls back to a generic Commons keyword search if that yields too
    few results. Returns up to `count` image dicts:
    {"url", "title", "artist", "license", "source_page"}.
    """
    images = _images_from_wikipedia_article(query, count)
    if len(images) < count:
        images += _images_from_commons_search(query, count)

    # De-dupe by file title (the same image can surface from both sources).
    seen = set()
    unique = []
    for image in images:
        if image["title"] in seen:
            continue
        seen.add(image["title"])
        unique.append(image)

    log(f"\t=> \"{query}\" found {len(unique)} usable Commons image(s)", "info")
    return unique[:count]
