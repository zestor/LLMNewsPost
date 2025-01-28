from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time
import subprocess
import os
import sys
import signal
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

try:
    import psutil
except ImportError:
    psutil = None

PID_FILE = os.path.expanduser("./post_news_chrome_pid.txt")

def slow_scroll(driver, 
                scroll_pause_time_min=2, 
                scroll_pause_time_max=6, 
                scroll_increment_min=1000, 
                scroll_increment_max=1000,
                max_scrolls=5, 
                verbose=True):
    try:
        # Get the initial scroll height
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0

        while True:
            scroll_increment = random.uniform(scroll_increment_min, scroll_increment_max)
            # Scroll down by the increment
            driver.execute_script(f"window.scrollBy(0, {scroll_increment});")
            scroll_count += 1

            if verbose:
                print(f"Scroll number {scroll_count}: Scrolled down by {scroll_increment} pixels.")

            # Wait for a random time between min and max pause time
            sleep_time = random.uniform(scroll_pause_time_min, scroll_pause_time_max)
            if verbose:
                print(f"Sleeping for {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)

            # Calculate new scroll height and compare with last scroll height
            new_height = driver.execute_script("return window.pageYOffset + window.innerHeight")
            total_height = driver.execute_script("return document.body.scrollHeight")

            if new_height >= total_height:
                if verbose:
                    print("Reached the bottom of the page.")
                break

            if max_scrolls is not None and scroll_count >= max_scrolls:
                if verbose:
                    print(f"Reached the maximum number of scrolls: {max_scrolls}")
                break

    except WebDriverException as e:
        print(f"WebDriverException occurred during scrolling: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during scrolling: {e}")

def launch_chrome():
    # Path to the Google Chrome executable
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    # Expand the user home directory (~) to the full path
    user_data_dir = os.path.expanduser("./chrome_linkedin_slave")

    # Define the remote debugging port
    remote_debugging_port = "9222"

    # Ensure the user data directory exists
    os.makedirs(user_data_dir, exist_ok=True)

    # Construct the command as a list
    cmd = [
        chrome_path,
        f"--remote-debugging-port={remote_debugging_port}",
        f"--user-data-dir={user_data_dir}"
    ]

    try:
        # Launch Chrome
        process = subprocess.Popen(cmd)
        pid = process.pid
        print(f"Google Chrome launched successfully with PID {pid}.")

        # Save the PID to a file for later reference
        with open(PID_FILE, "w") as f:
            f.write(str(pid))
        print(f"PID saved to {PID_FILE}.")

    except FileNotFoundError:
        print("Google Chrome executable not found. Please check the path.")
    except Exception as e:
        print(f"An error occurred while launching Chrome: {e}")

def kill_chrome():
    if not os.path.exists(PID_FILE):
        print(f"No PID file found at {PID_FILE}. Is Chrome running?")
        return

    try:
        with open(PID_FILE, "r") as f:
            pid_str = f.read().strip()
            pid = int(pid_str)
    except Exception as e:
        print(f"Failed to read PID file: {e}")
        return

    try:
        if psutil:
            proc = psutil.Process(pid)
            # Terminate the process and its children
            proc.terminate()
            try:
                proc.wait(timeout=10)
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
        os.remove(PID_FILE)
        print(f"PID file {PID_FILE} removed.")
    except ProcessLookupError:
        print(f"No process found with PID {pid}. It might have already terminated.")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            print(f"PID file {PID_FILE} removed.")
    except PermissionError:
        print(f"Permission denied when trying to kill process {pid}.")
    except Exception as e:
        print(f"An error occurred while trying to kill Chrome: {e}")

launch_chrome()

# Attach Selenium to an existing browser session
options = webdriver.ChromeOptions()
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")  # Ensure your browser is launched with this debugging port
driver = webdriver.Chrome(options=options)

# Navigate to LinkedIn feed
driver.get("https://www.linkedin.com/feed/")

# Wait for the page to load
time.sleep(5)

slow_scroll(driver)

# Extract page source and parse with BeautifulSoup
soup = BeautifulSoup(driver.page_source, "html.parser")

# Scrape posts from the feed (adjust selectors based on LinkedIn's HTML structure)
posts = soup.find_all("div", class_="update-components-text relative update-components-update-v2__commentary")  # Example class; inspect LinkedIn's page source for accuracy
#texts = soup.find_all("span", class_="ltr")
print(f"Found {len(posts)} posts")
for post in posts:
    content = post.get_text(strip=True)
    content = f"```LinkedIn Post\n\n{content}\n\n```\n\n"
    print(content)

time.sleep(5)

# Close the browser when done
driver.quit()

time.sleep(5)

kill_chrome()
