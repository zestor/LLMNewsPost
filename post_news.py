
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from openai import OpenAI
import subprocess
import requests
from collections import defaultdict
import concurrent.futures
from firecrawl import FirecrawlApp
import time
import random
import hashlib


PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "...")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "...")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "...")

client = OpenAI()
client.api_key = OPENAI_API_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

CACHE_DIR = 'post_news_cache'
    
def call_firecrawl_scrape(retrieve_url: str) -> str:
    retval = ""
    try:
        #app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
        #retval = app.scrape_url(url, params={'formats': ['markdown']})

        url = "https://api.firecrawl.dev/v1/scrape"

        payload = {
            "url": retrieve_url,
            "formats": ["markdown"],
            "waitFor": 0,
            "skipTlsVerification": False,
            "timeout": 180000,
            "removeBase64Images": True
        }
        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json"
        }

        retval = requests.request("POST", url, json=payload, headers=headers)
        retval = retval.text

        print(f"Firecrawl response\n\n{retval}")

    except Exception as e:
        retval = f"Error returning markdown data from {retrieve_url}: {str(e)}"
    return retval

def get_post(query: str) -> str:
    # month, week, day, hour.
    perplexity_responses = generate_perplexity_responses(query, 10)
    report = ""
    for perplexity_response in perplexity_responses:
        report += f"\n```Article\n{perplexity_response}\n```\n"
    initial_answers = generate_initial_answers(report, 8)
    return rank_answers(initial_answers)

def get_huggingface_papers(days_in_past: int) -> List[str]:
    results = []
    base_url = "https://huggingface.co/papers"
    today = date.today()
    for offset in range(0,days_in_past):
        date_str = (today - timedelta(days=offset)).strftime('%Y-%m-%d')
        url = f"{base_url}?date={date_str}"
        print(f"Fetching {date_str}...")
        try:
            response = call_firecrawl_scrape(retrieve_url=url)
            pattern = r'https?://huggingface\.co/papers/(\d+\.\d+)'
            paper_ids = re.findall(pattern, response)
            # Unique
            paper_ids = list(dict.fromkeys(paper_ids))
            for paper_id in paper_ids:
                arxiv_pdf_url = f"https://arxiv.org/pdf/{paper_id}"
                
                if not os.path.exists(CACHE_DIR):
                    os.makedirs(CACHE_DIR)

                hash_url = hashlib.sha256(arxiv_pdf_url.encode()).hexdigest()
                cache_path = os.path.join(CACHE_DIR, hash_url)
                
                if os.path.isfile(cache_path):
                    print(f"Fetching Cache {arxiv_pdf_url}...")
                    with open(cache_path, 'r') as f:
                        summary = f.readlines()
                else:
                    print(f"Fetching Realtime {arxiv_pdf_url}...")
                    response = call_firecrawl_scrape(retrieve_url=arxiv_pdf_url)
                    print(f"Summarizing {arxiv_pdf_url}...")
                    summary = call_openai(f"Gently summarize this without missing any detail.\n\n{response}")
                    summary = f"Arxiv Research Paper Posted {date_str}\n\n{summary}"
                    with open(cache_path, 'w') as f:
                        f.write(summary)
                    wait_time = random.uniform(5, 10)
                    print(f"Waiting {wait_time} ...")
                    time.sleep(wait_time)

                print(summary)
                results.append(summary)

        except requests.RequestException as e:
            print(f"Error: {e}")
    return results

def generate_perplexity_responses(query: str, n: int) -> List[str]:
    perplexity_responses = []
    hf_papers = get_huggingface_papers(days_in_past=1)
    perplexity_responses.append(hf_papers)
    print("Generating perplexity responses in parallel...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(call_perplexity, query, "day") for _ in range(n)]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            answer = future.result()
            date_str = date.today().strftime('%Y-%m-%d')
            answer = f"News Article Posted {date_str}\n\n{answer}"
            perplexity_responses.append(answer)
            print(f"Generated preplexity response {i + 1}")
    print(f"Generated {len(perplexity_responses)} answers.\n")
    return perplexity_responses

def generate_initial_answers(report: str, n: int) -> List[str]:
    initial_answers = []
    prompt = f"""
    Today is {get_current_datetime()}
    Write today's AI news by consolidating new arxiv papers and news story without missing any detail, cite all sources as links [Read more](<citation source>). 
    Important: Don't miss any arxiv paper or news story.
    Response document # title must be 'AI News for <date>', where <date> is today's date in the format, MM-DD-YYYY.
    Response each arxiv paper or news story identified as such with it's own ## tag with accompanying details.
    ```Context
    {report}
    ```
    """
    print("Generating initial answers in parallel...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(call_openai, prompt) for _ in range(n)]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            answer = future.result()
            initial_answers.append(answer)
            print(f"Generated answer {i + 1}")
    print(f"Generated {len(initial_answers)} answers.\n")
    return initial_answers

def rank_answers(initial_answers: List[str]) -> str:
    round_number = 1
    current_round = initial_answers.copy()
    
    while len(current_round) > 1:
        print(f"Starting Round {round_number} with {len(current_round)} competitors.")
        next_round = []
        
        # Ensure the number of answers is even
        if len(current_round) % 2 != 0:
            # If odd, automatically advance the last answer to the next round
            print("Odd number of answers. Automatically advancing the last answer to the next round.")
            next_round.append(current_round[-1])
            current_round = current_round[:-1]
        
        for i in range(0, len(current_round), 2):
            a = current_round[i]
            b = current_round[i + 1]
            print(f"Comparing Answer {i + 1} vs. Answer {i + 2}...")
            result = compare_answers(a, b)
            if result == 'A':
                print("Answer A wins the comparison.\n")
                next_round.append(a)
            elif result == 'B':
                print("Answer B wins the comparison.\n")
                next_round.append(b)
            else:
                # Handle unexpected results by defaulting or implementing retry logic
                print("Unexpected result. Defaulting to Answer A.\n")
                next_round.append(a)
        
        current_round = next_round
        print(f"Round {round_number} completed. {len(current_round)} answers advancing to the next round.\n")
        round_number += 1
    
    best_answer = current_round[0]
    print("Tournament completed. Best answer selected.\n")
    return best_answer

def compare_answers(a, b):
    retval = 'A'
    comparison_prompt = f"""
Which is the best answer A or B with the most and best stories for answering the query "Today's AI News." Respond only A or B. 

```A
{a}
```

```B
{b}
```
"""
    response = call_openai(comparison_prompt, model="gpt-4o").strip().upper()

    if 'B' in response or 'b' in response:
        retval = 'B'

    print(f"\nLLM as judge picked: {retval}")
    return retval

def get_current_datetime() -> str:
    now = datetime.now()
    formatted_time = now.strftime("%A, %B %d, %Y, %H:%M:%S")
    return f"Current date and time: {formatted_time}"

def call_openai(prompt: str, model: str = "o1-mini", messages: Optional[List[Dict[str, str]]] = None) -> str:
    """
    Calls LLM for advanced reasoning or sub-queries.
    """
    helper_messages = []

    if messages is None:
        helper_messages = [
            {'role': 'user', 'content': get_current_datetime() + '\n' + prompt}
        ]
    else:
        helper_messages = messages.copy()
        # Append the user message if messages were provided
        helper_messages.append({'role': 'user', 'content': prompt})
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=helper_messages
        )

        return completion.choices[0].message.content
    except Exception as e:
        return f"Error calling LLM model='{model}': {str(e)}"

def call_perplexity(query: str, recency: str = "day") -> str:
    """
    Calls the Perplexity AI API with the given query.
    Returns the text content from the model’s answer.
    """
    url = "https://api.perplexity.ai/chat/completions"
    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "user", "content": query},
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "search_recency_filter": recency,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        retval = data["choices"][0]["message"]["content"]
        citations_list = data.get("citations", [])
        numbered_citations = "\n".join(f"{i + 1}. {citation}" for i, citation in enumerate(citations_list))
        citations = f"\n\nCitations:\n{numbered_citations}"
        retval = retval + citations

        print(f"* * *  Research Assistant Response  * * *\n\n{retval}\n\n")
        return retval
    except Exception as e:
        return f"Error calling Perplexity API: {str(e)}"

def extract_title(markdown_content: str) -> str:
    """
    Extracts the title from the first Markdown heading.

    Args:
        markdown_content (str): The Markdown content.

    Returns:
        str: The extracted title or 'Untitled' if not found.
    """
    match = re.search(r'^#\s+(.*)', markdown_content, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        logging.info(f"Extracted title: '{title}'")
        return title
    else:
        logging.warning("No Markdown heading found. Using default title 'Untitled'.")
        return "Untitled"

def construct_payload(title: str, content: str) -> Dict:
    payload = {
        "title": f"{title}",
        "content": f"""{content}"""
    }
    return payload

def post_article(payload) -> None:
    url = 'https://www.chrisclark.com/create_markdown_post.php'

    # Convert payload to JSON string
    payload_json = json.dumps(payload)

    # Construct the curl command
    curl_command = [
        "curl",
        "--location",
        url,
        "-H", "Content-Type: application/json",
        "-d", payload_json
    ]

    try:
        # Execute the curl command
        result = subprocess.run(curl_command, capture_output=True, text=True)

        # Check for errors
        if result.returncode != 0:
            logging.error(f"curl command failed with error: {result.stderr.strip()}")
            return

        # Print status code and response body
        # To get the status code, you'll need to modify the curl command to include it
        # One way is to use the -w flag to write out the HTTP status
        # Here's an alternative approach:

        # Reconstruct curl command to capture status code
        curl_command_with_status = [
            "curl",
            "--location",
            url,
            "-H", "Content-Type: application/json",
            "-d", payload_json,
            "-w", "%{http_code}"
        ]
        result_with_status = subprocess.run(curl_command_with_status, capture_output=True, text=True)

        if result_with_status.returncode != 0:
            logging.error(f"curl command failed with error: {result_with_status.stderr.strip()}")
            return

        response_body = result_with_status.stdout[:-3]  # Exclude the last 3 digits which are the status code
        status_code = result_with_status.stdout[-3:]

        print("Status Code:", status_code)
        print("Response Body:", response_body)

    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to execute curl command: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

def main():

    content = get_post("""Recent Today's News on Generative AI and Artificial Intelligence (AI) and Large Language Model (LLM). Note 3-4 facts from each story.""")
    title = extract_title(content)

    if not title:
        logging.error("Title cannot be empty.")
        sys.exit(1)
    if not content:
        logging.error("Content cannot be empty.")
        sys.exit(1)

    payload = construct_payload(title, content)
    print(json.dumps(payload, indent=4))  # For debugging purposes
    post_article(payload)

if __name__ == "__main__":
    main()
