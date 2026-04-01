"""
core/scraper.py

Instagram scraper using Playwright with a persistent browser session.

Requires a pre-authenticated browser profile in ig_profile/ (created by login.py).
Runs in headless mode for all scraping operations.

Two public functions:
  - scrape_reels()   — scrolls a profile's reels tab and returns reel URLs
  - get_reel_audio() — visits each reel URL and extracts the audio/song label

If the scraper stops finding new reels for 8 consecutive scroll rounds, it exits.
If running in update mode (known_urls provided), it also exits after 3 consecutive
rounds where all found reels are already known — avoiding a full profile re-scroll.
"""

import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

# Resolve ig_profile/ relative to the project root (one level up from core/)
ROOT = Path(__file__).parent.parent
PROFILE_DIR = str(ROOT / "ig_profile")


def _try_click(locator, pause_ms=500):
    """Attempts to click a Playwright locator. Returns True if clicked, False otherwise."""
    try:
        if locator.count():
            try:
                locator.first.click(timeout=1500)
                locator.page.wait_for_timeout(pause_ms)
                return True
            except Exception:
                return False
    except Exception:
        return False
    return False


def _dismiss_cookies(page):
    """
    Attempts to dismiss cookie consent dialogs that Instagram shows on page load.
    Tries multiple button texts and also checks iframes.
    Safe to call even if no dialog is present — all attempts fail silently.
    """
    texts = [
        "Allow all cookies",
        "Allow essential and optional cookies",
        "Accept all",
        "Accept",
        "Allow",
        "Only allow essential cookies",
        "Decline optional cookies",
        "Agree",
        "OK",
    ]

    for text in texts:
        if _try_click(page.get_by_role("button", name=text)):
            return
        if _try_click(page.get_by_text(text, exact=True)):
            return

    dialog = page.locator("div[role='dialog']")
    if dialog.count():
        for token in ["allow", "accept", "agree", "ok"]:
            if _try_click(dialog.get_by_role("button", name=re.compile(token, re.I))):
                return

    if _try_click(page.locator("button:has-text('cookie')")):
        return

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            for text in texts:
                if _try_click(frame.get_by_role("button", name=text)):
                    return
                if _try_click(frame.get_by_text(text, exact=True)):
                    return
        except Exception:
            continue


def _ensure_profile_exists(profile_dir):
    """Raises if the browser profile directory doesn't exist."""
    if not os.path.exists(profile_dir):
        raise RuntimeError(
            f"Instagram profile not found: {profile_dir}. "
            "Run login.py to create it."
        )


def scrape_reels(username, max_scrolls=500, profile_dir=PROFILE_DIR, known_urls=None):
    """
    Scrolls the Instagram reels tab for the given username and returns new reel URLs.

    Args:
        username:    Instagram handle to scrape (without @)
        max_scrolls: Hard cap on scroll iterations — safety net for huge profiles.
                     The stagnation logic will exit sooner in normal cases.
        profile_dir: Path to the Playwright persistent browser profile
        known_urls:  Set of URLs already in songs.json. If provided, the scraper
                     exits early once it hits 3 consecutive rounds of only-known reels.

    Returns:
        List of reel URLs not in known_urls (new reels only).
    """
    _ensure_profile_exists(profile_dir)
    known = set(known_urls or [])

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            locale="en-US",
        )
        page = context.new_page()
        page.set_default_timeout(20000)

        page.goto(
            f"https://www.instagram.com/{username}/reels/",
            wait_until="domcontentloaded",
        )
        _dismiss_cookies(page)

        seen = set()
        stagnant_rounds = 0
        known_stagnant_rounds = 0
        scrolls = 0

        while stagnant_rounds < 8 and scrolls < max_scrolls:
            # Only grab links belonging to this profile — filters out Instagram's
            # "suggested reels" from other accounts that appear as you scroll
            links = page.eval_on_selector_all(
                "a[href*='/reel/']",
                f"els => els.map(e => e.href).filter(h => h.includes('/{username}/'))",
            )
            new = set(links) - seen

            if not new:
                stagnant_rounds += 1
                print(f"\r  scroll {scrolls+1}/{max_scrolls} | {len(seen)} reels | stagnant {stagnant_rounds}/8   ", end="", flush=True)
            else:
                stagnant_rounds = 0
                seen.update(new)
                truly_new = new - known

                if known and not truly_new:
                    known_stagnant_rounds += 1
                    print(f"\r  scroll {scrolls+1}/{max_scrolls} | {len(seen)} reels (all known, {known_stagnant_rounds}/3)   ", end="", flush=True)
                    if known_stagnant_rounds >= 3:
                        break
                else:
                    known_stagnant_rounds = 0
                    print(f"\r  scroll {scrolls+1}/{max_scrolls} | {len(seen)} reels (+{len(truly_new)} new)   ", end="", flush=True)

            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(4000)
            scrolls += 1

        new_reels = [u for u in seen if u not in known]
        print(f"\r  Done. {len(new_reels)} new reels (of {len(seen)} total found)                    ")
        context.close()
        return new_reels


def _extract_audio_label(page):
    """
    Extracts the audio/song label from a reel page.
    Returns "UNKNOWN" if no audio label is found.
    """
    selectors = [
        "a[href*='/audio/'] span",
        "a[href*='/audio/']",
        "a[href*='/music/'] span",
        "a[href*='/music/']",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            text = (loc.first.text_content() or "").strip()
            if text:
                return text

    loc = page.locator("a:has-text('audio')")
    if loc.count():
        text = (loc.first.text_content() or "").strip()
        if text:
            return text

    return "UNKNOWN"


def get_reel_audio(links, profile_dir=PROFILE_DIR):
    """
    Visits each reel URL and extracts the audio label.

    Returns:
        List of (url, audio_label) tuples.
    """
    _ensure_profile_exists(profile_dir)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            locale="en-US",
        )
        page = context.new_page()
        page.set_default_timeout(20000)

        results = []
        total = len(links)
        for i, url in enumerate(links, 1):
            try:
                page.goto(url, wait_until="domcontentloaded")
                _dismiss_cookies(page)
                audio = _extract_audio_label(page)
            except Exception:
                audio = "UNKNOWN"
            results.append((url, audio))
            print(f"\r  [{i}/{total}] {audio}                              ", end="", flush=True)
            page.wait_for_timeout(800)

        print()
        context.close()
        return results
