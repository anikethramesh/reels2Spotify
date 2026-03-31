import os
import re
from playwright.async_api import async_playwright


PROFILE_DIR = "ig_profile"


async def _try_click(locator, pause_ms=500):
    try:
        if await locator.count():
            try:
                await locator.first.click(timeout=1500)
                await locator.page.wait_for_timeout(pause_ms)
                return True
            except Exception:
                return False
    except Exception:
        return False
    return False


async def _dismiss_cookies(page):
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
        if await _try_click(page.get_by_role("button", name=text)):
            return
        if await _try_click(page.get_by_text(text, exact=True)):
            return

    dialog = page.locator("div[role='dialog']")
    if await dialog.count():
        for token in ["allow", "accept", "agree", "ok"]:
            if await _try_click(dialog.get_by_role("button", name=re.compile(token, re.I))):
                return

    if await _try_click(page.locator("button:has-text('cookie')")):
        return

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            for text in texts:
                if await _try_click(frame.get_by_role("button", name=text)):
                    return
                if await _try_click(frame.get_by_text(text, exact=True)):
                    return
        except Exception:
            continue


def _ensure_profile_exists(profile_dir):
    if not os.path.exists(profile_dir):
        raise RuntimeError(
            f"Instagram profile not found: {profile_dir}. "
            "Run a manual login to create it before using the API."
        )


async def scrape_reels(username, max_scrolls=500, profile_dir=PROFILE_DIR):
    _ensure_profile_exists(profile_dir)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            locale="en-US",
        )
        page = await context.new_page()
        page.set_default_timeout(20000)

        await page.goto(
            f"https://www.instagram.com/{username}/reels/",
            wait_until="domcontentloaded",
        )
        await _dismiss_cookies(page)

        seen = set()
        stagnant_rounds = 0
        scrolls = 0
        while stagnant_rounds < 8 and scrolls < max_scrolls:
            links = await page.eval_on_selector_all(
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
                print(f"\r  scroll {scrolls+1}/{max_scrolls} | {len(seen)} reels (+{len(new)})   ", end="", flush=True)

            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(4000)
            scrolls += 1

        print(f"\r  Done. Total reels found: {len(seen)}                    ")
        await context.close()
        return list(seen)


async def _extract_audio_label(page):
    selectors = [
        "a[href*='/audio/'] span",
        "a[href*='/audio/']",
        "a[href*='/music/'] span",
        "a[href*='/music/']",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if await loc.count():
            text = (await loc.first.text_content() or "").strip()
            if text:
                return text

    loc = page.locator("a:has-text('audio')")
    if await loc.count():
        text = (await loc.first.text_content() or "").strip()
        if text:
            return text
    return "UNKNOWN"


async def get_reel_audio(links, profile_dir=PROFILE_DIR):
    _ensure_profile_exists(profile_dir)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            locale="en-US",
        )
        page = await context.new_page()
        page.set_default_timeout(20000)

        results = []
        total = len(links)
        for i, url in enumerate(links, 1):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await _dismiss_cookies(page)
                audio = await _extract_audio_label(page)
            except Exception:
                audio = "UNKNOWN"
            results.append((url, audio))
            print(f"\r  [{i}/{total}] {audio}                              ", end="", flush=True)
            await page.wait_for_timeout(800)

        print()
        await context.close()
        return results
