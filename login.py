"""
Run this script once to create/refresh the Instagram session profile.
A visible browser window will open — log in manually, then press Enter here.
"""
import asyncio
import shutil
import os
from playwright.async_api import async_playwright

PROFILE_DIR = "ig_profile"


async def main():
    if os.path.exists(PROFILE_DIR):
        ans = input(f"'{PROFILE_DIR}' already exists. Delete and recreate? [y/N] ").strip().lower()
        if ans == "y":
            shutil.rmtree(PROFILE_DIR)
            print("Deleted old profile.")
        else:
            print("Keeping existing profile. Opening browser to verify session...")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            locale="en-US",
        )
        page = await context.new_page()
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")

        print("\nBrowser is open. Log in to Instagram if prompted.")
        print("Once you're logged in and can see your feed, come back here and press Enter.")
        input("Press Enter to save session and exit...")

        await context.close()
    print(f"Session saved to '{PROFILE_DIR}'. You can now run main.py.")


if __name__ == "__main__":
    asyncio.run(main())
