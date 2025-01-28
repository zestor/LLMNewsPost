import os
import sys
import time
import random
import signal
import subprocess
import shutil
from typing import List
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    WebDriverException,
    SessionNotCreatedException,
)
from bs4 import BeautifulSoup

try:
    import psutil
except ImportError:
    psutil = None


class LinkedInScraper:
    # File and Path Constants
    PID_FILE = os.path.expanduser("./post_news_chrome_pid.txt")
    CHROME_PATH = "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev"
    USER_DATA_DIR = os.path.expanduser("./post_news_chrome_state")

    # Network and URL Constants
    REMOTE_DEBUGGING_PORT = "9222"
    LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

    # Scrolling Constants
    DEFAULT_SCROLL_PAUSE_TIME_MIN = 2  # Minimum pause time between scrolls in seconds
    DEFAULT_SCROLL_PAUSE_TIME_MAX = 5  # Maximum pause time between scrolls in seconds
    DEFAULT_SCROLL_INCREMENT_MIN = 1000  # Minimum pixels to scroll per increment
    DEFAULT_SCROLL_INCREMENT_MAX = 1000  # Maximum pixels to scroll per increment
    DEFAULT_MAX_SCROLLS = 30  # Maximum number of scrolls

    # Process Management Constants
    CHROME_TERMINATION_TIMEOUT = 10  # Timeout in seconds for terminating Chrome
    TERMINATION_SLEEP_DURATION = 5  # Sleep duration in seconds before killing Chrome

    # WebDriver Constants
    WEBDRIVER_SLEEP_AFTER_NAVIGATION = 5  # Sleep time after navigating to the feed

    # Messaging Constants
    ERROR_WEB_DRIVER_NOT_INITIALIZED = "WebDriver is not initialized."
    ERROR_GOOGLE_CHROME_NOT_FOUND = "Google Chrome executable not found. Please check the CHROME_PATH."
    ERROR_LAUNCHING_CHROME = "An error occurred while launching Chrome: {}"
    ERROR_CONNECTING_WEBDRIVER = "Failed to connect WebDriver to Chrome: {}"
    ERROR_STARTING_WEBDRIVER = "An unexpected error occurred while starting WebDriver: {}"
    ERROR_SCRAPING = "An error occurred during scraping: {}"
    ERROR_QUITTING_WEBDRIVER = "Error while quitting WebDriver: {}"
    ERROR_READING_PID_FILE = "Failed to read PID file: {}"
    ERROR_KILLING_CHROME = "An error occurred while trying to kill Chrome: {}"
    ERROR_ENVIRONMENT_SETUP = "Environment setup error: {}"

    def __init__(
        self,
        scroll_pause_time_min=DEFAULT_SCROLL_PAUSE_TIME_MIN,
        scroll_pause_time_max=DEFAULT_SCROLL_PAUSE_TIME_MAX,
        scroll_increment_min=DEFAULT_SCROLL_INCREMENT_MIN,
        scroll_increment_max=DEFAULT_SCROLL_INCREMENT_MAX,
        max_scrolls=DEFAULT_MAX_SCROLLS,
        verbose=True,
    ):
        self.scroll_pause_time_min = scroll_pause_time_min
        self.scroll_pause_time_max = scroll_pause_time_max
        self.scroll_increment_min = scroll_increment_min
        self.scroll_increment_max = scroll_increment_max
        self.max_scrolls = max_scrolls
        self.verbose = verbose
        self.driver = None

        # Validate environment
        self._validate_environment()

    def _validate_environment(self):
        """
        Validate that all necessary components and paths are set up correctly.
        """
        # Check if Chrome executable exists
        if not self.CHROME_PATH or not os.path.isfile(self.CHROME_PATH):
            print(self.ERROR_GOOGLE_CHROME_NOT_FOUND)
            sys.exit(1)

        # Check if user has necessary permissions for USER_DATA_DIR
        try:
            os.makedirs(self.USER_DATA_DIR, exist_ok=True)
            test_file = os.path.join(self.USER_DATA_DIR, "test_permission")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except PermissionError:
            print(
                self.ERROR_ENVIRONMENT_SETUP.format(
                    f"Insufficient permissions for directory {self.USER_DATA_DIR}."
                )
            )
            sys.exit(1)
        except Exception as e:
            print(self.ERROR_ENVIRONMENT_SETUP.format(e))
            sys.exit(1)

        # Check if required Python packages are installed
        required_packages = ["selenium", "bs4"]
        missing_packages = []
        for pkg in required_packages:
            if not self._is_package_installed(pkg):
                missing_packages.append(pkg)
        if missing_packages:
            print(
                self.ERROR_ENVIRONMENT_SETUP.format(
                    f"Missing packages: {', '.join(missing_packages)}. Please install them."
                )
            )
            sys.exit(1)

    @staticmethod
    def _is_package_installed(package_name: str) -> bool:
        """
        Check if a Python package is installed.
        """
        import importlib

        spec = importlib.util.find_spec(package_name)
        return spec is not None

    def _slow_infinite_scroll(self):
        try:
            if not self.driver:
                raise WebDriverException(self.ERROR_WEB_DRIVER_NOT_INITIALIZED)

            # Get the initial scroll height
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0

            while True:
                scroll_increment = random.uniform(
                    self.scroll_increment_min, self.scroll_increment_max
                )
                # Scroll down by the increment
                self.driver.execute_script(
                    f"window.scrollBy(0, {scroll_increment});"
                )
                scroll_count += 1

                if self.verbose:
                    print(
                        f"Scroll number {scroll_count}: Scrolled down by {scroll_increment} pixels."
                    )

                # Wait for a random time between min and max pause time
                sleep_time = random.uniform(
                    self.scroll_pause_time_min, self.scroll_pause_time_max
                )
                if self.verbose:
                    print(f"Sleeping for {sleep_time:.2f} seconds.")
                time.sleep(sleep_time)

                # Calculate new scroll height and compare with last scroll height
                new_height = self.driver.execute_script(
                    "return window.pageYOffset + window.innerHeight"
                )
                total_height = self.driver.execute_script(
                    "return document.body.scrollHeight"
                )

                if new_height >= total_height:
                    if self.verbose:
                        print("Reached the bottom of the page.")
                    break

                if self.max_scrolls is not None and scroll_count >= self.max_scrolls:
                    if self.verbose:
                        print(f"Reached the maximum number of scrolls: {self.max_scrolls}")
                    break

        except WebDriverException as e:
            print(f"WebDriverException occurred during scrolling: {e}")
        except Exception as e:
            print(f"An unexpected error occurred during scrolling: {e}")

    def _launch_chrome(self):
        # Ensure the user data directory exists
        try:
            os.makedirs(self.USER_DATA_DIR, exist_ok=True)
        except Exception as e:
            print(
                self.ERROR_ENVIRONMENT_SETUP.format(
                    f"Failed to create user data directory: {e}"
                )
            )
            sys.exit(1)

        # Construct the command as a list
        cmd = [
            self.CHROME_PATH,
            f"--remote-debugging-port={self.REMOTE_DEBUGGING_PORT}",
            f"--user-data-dir={self.USER_DATA_DIR}",
        ]

        try:
            # Launch Chrome
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            pid = process.pid
            print(f"Google Chrome launched successfully with PID {pid}.")

            # Save the PID to a file for later reference
            with open(self.PID_FILE, "w") as f:
                f.write(str(pid))
            print(f"PID saved to {self.PID_FILE}.")

        except FileNotFoundError:
            print(self.ERROR_GOOGLE_CHROME_NOT_FOUND)
            sys.exit(1)
        except PermissionError:
            print(
                self.ERROR_ENVIRONMENT_SETUP.format(
                    "Permission denied when trying to launch Chrome."
                )
            )
            sys.exit(1)
        except Exception as e:
            print(self.ERROR_LAUNCHING_CHROME.format(e))
            sys.exit(1)

    def _kill_chrome(self):
        if not os.path.exists(self.PID_FILE):
            if self.verbose:
                print(f"No PID file found at {self.PID_FILE}. Is Chrome running?")
            return

        try:
            with open(self.PID_FILE, "r") as f:
                pid_str = f.read().strip()
                pid = int(pid_str)
        except Exception as e:
            print(self.ERROR_READING_PID_FILE.format(e))
            return

        try:
            if psutil:
                proc = psutil.Process(pid)
                # Terminate the process and its children
                proc.terminate()
                try:
                    proc.wait(timeout=self.CHROME_TERMINATION_TIMEOUT)
                    print(f"Process {pid} terminated successfully.")
                except psutil.TimeoutExpired:
                    proc.kill()
                    print(f"Process {pid} killed forcefully.")
            else:
                # Fallback to os.kill if psutil is not available
                os.kill(pid, signal.SIGTERM)
                print(f"Sent termination signal to process {pid}.")
                # Optionally, wait and confirm termination
                time.sleep(2)
                try:
                    os.kill(pid, 0)  # Check if process is still alive
                    print(f"Process {pid} is still running. Attempting to kill.")
                    os.kill(pid, signal.SIGKILL)
                    print(f"Process {pid} killed successfully.")
                except OSError:
                    print(f"Process {pid} terminated.")
            # Remove the PID file after successful termination
            os.remove(self.PID_FILE)
            print(f"PID file {self.PID_FILE} removed.")
        except ProcessLookupError:
            print(
                f"No process found with PID {pid}. It might have already terminated."
            )
            if os.path.exists(self.PID_FILE):
                os.remove(self.PID_FILE)
                print(f"PID file {self.PID_FILE} removed.")
        except PermissionError:
            print(f"Permission denied when trying to kill process {pid}.")
        except Exception as e:
            print(self.ERROR_KILLING_CHROME.format(e))

    def _start_driver(self):
        try:
            # Configure Chrome options to connect to the existing Chrome instance
            options = webdriver.ChromeOptions()
            options.add_experimental_option(
                "debuggerAddress", f"127.0.0.1:{self.REMOTE_DEBUGGING_PORT}"
            )
            options.add_argument("--no-sandbox")  # Add more options as needed for your environment
            options.add_argument(
                "--disable-dev-shm-usage"
            )  # Overcome limited resource problems

            # Initialize the WebDriver
            self.driver = webdriver.Chrome(options=options)
            print("WebDriver connected to the Chrome instance.")

        except SessionNotCreatedException as e:
            print(self.ERROR_CONNECTING_WEBDRIVER.format("Session not created. " + str(e)))
            self._kill_chrome()
            sys.exit(1)
        except WebDriverException as e:
            print(self.ERROR_CONNECTING_WEBDRIVER.format(e))
            self._kill_chrome()
            sys.exit(1)
        except Exception as e:
            print(self.ERROR_STARTING_WEBDRIVER.format(e))
            self._kill_chrome()
            sys.exit(1)

    def _scrape_posts(self) -> List[str]:
        posts = []
        if not self.driver:
            print(self.ERROR_WEB_DRIVER_NOT_INITIALIZED)
            return posts  # Return empty list instead of None

        try:
            # Navigate to LinkedIn feed
            self.driver.get(self.LINKEDIN_FEED_URL)
            print(f"Navigated to {self.LINKEDIN_FEED_URL}")

            # Wait for the page to load
            time.sleep(self.WEBDRIVER_SLEEP_AFTER_NAVIGATION)

            #stuff = input("Pause to get Chrome logged in and have no issues getting to LinkedIn")

            # Perform slow scrolling
            self._slow_infinite_scroll()

            # Extract page source and parse with BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            # Scrape posts from the feed (adjust selectors based on LinkedIn's HTML structure)
            post_elements = soup.find_all(
                "div",
                class_="update-components-text relative update-components-update-v2__commentary",
            )

            if self.verbose:
                print(f"Found {len(post_elements)} posts")

            for post in post_elements:
                content = post.get_text(strip=True)
                formatted_content = f"```LinkedIn Post\n\n{content}\n\n```\n\n"
                posts.append(formatted_content)

        except Exception as e:
            print(self.ERROR_SCRAPING.format(e))

        return posts

    def run(self) -> List[str]:
        posts = []

        try:
            self._launch_chrome()
            self._start_driver()
            posts = self._scrape_posts()

        except KeyboardInterrupt:
            print("Process interrupted by user.")

        finally:
            # Ensure that resources are cleaned up properly
            if self.driver:
                try:
                    self.driver.quit()
                    print("WebDriver session closed.")
                except Exception as e:
                    print(self.ERROR_QUITTING_WEBDRIVER.format(e))
            time.sleep(self.TERMINATION_SLEEP_DURATION)  # Optional: Wait before killing Chrome
            self._kill_chrome()

        return posts


if __name__ == "__main__":
    scraper = LinkedInScraper(
        scroll_pause_time_min=LinkedInScraper.DEFAULT_SCROLL_PAUSE_TIME_MIN,
        scroll_pause_time_max=LinkedInScraper.DEFAULT_SCROLL_PAUSE_TIME_MAX,
        scroll_increment_min=LinkedInScraper.DEFAULT_SCROLL_INCREMENT_MIN,
        scroll_increment_max=LinkedInScraper.DEFAULT_SCROLL_INCREMENT_MAX,
        max_scrolls=LinkedInScraper.DEFAULT_MAX_SCROLLS,
        verbose=True,
    )
    scraped_posts = scraper.run()

    # Optionally, handle the scraped_posts as needed
    if scraped_posts:
        print(f"Scraped {len(scraped_posts)} posts.")
    else:
        print("No posts were scraped.")
