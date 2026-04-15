import asyncio
from playwright.async_api import async_playwright
import os
from dotenv import load_dotenv, set_key

class InteractiveXHSLogin:
    def __init__(self):
        self.home_url = 'https://www.xiaohongshu.com/explore'
        self.env_file = '.env'

    async def interactive_login(self):
        """
        Open a browser window for manual login, then save cookies to .env file
        """
        print("=== Interactive Xiaohongshu Login ===")
        print("A browser window will open. Please log in to your Xiaohongshu account manually.")
        print("After you have successfully logged in, come back to this terminal and press Enter.")
        print()

        cookies_str = None

        async with async_playwright() as p:
            # Launch browser in headed mode so user can interact
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto(self.home_url)

            # Wait for user to confirm login is complete
            input("Press Enter AFTER you have logged in... ")

            # Get all cookies from the browser context
            cookies = await context.cookies()
            cookies_dict = {}
            for cookie in cookies:
                cookies_dict[cookie['name']] = cookie['value']

            # Convert to the required string format
            cookies_str = ''
            for key, value in cookies_dict.items():
                cookies_str += f'{key}={value}; '
            if cookies_str:
                cookies_str = cookies_str[:-2]

            await browser.close()

        if cookies_str and 'a1' in cookies_str:
            print(f"\nSuccessfully captured cookies!")
            print(f"Found a1 cookie: {'a1' in cookies_dict}")
            print(f"Total cookies captured: {len(cookies_dict)}")

            # Save to .env file
            self.save_cookies_to_env(cookies_str)
            print(f"\nCookies have been automatically saved to {self.env_file}")
            print("You can now run the scraper - no need to manually copy cookies!")
            return cookies_str
        else:
            print("\nWarning: No cookies captured or missing required 'a1' cookie.")
            print("Please try again and make sure you are fully logged in.")
            return None

    def save_cookies_to_env(self, cookies_str):
        """Save cookies to .env file"""
        # Check if .env exists, create if not
        if not os.path.exists(self.env_file):
            with open(self.env_file, 'w') as f:
                f.write(f"XHS_COOKIES={cookies_str}\n")
            return

        # Load existing env and update
        load_dotenv(self.env_file)
        set_key(self.env_file, 'XHS_COOKIES', cookies_str)

if __name__ == '__main__':
    login_helper = InteractiveXHSLogin()
    asyncio.run(login_helper.interactive_login())
