import feedparser
from bs4 import BeautifulSoup
import requests
import time
import os
import logging
import sys
import json
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,  # Logging to stdout
)

# Get login and password from environment variables
blue_login = os.getenv("BLUE_LOGIN", "user")
blue_password = os.getenv("BLUE_PASSWORD", "password")

# Get the current Unix time and subtract 604800 seconds (1 week) as the default value
default_unix_time = int(time.time()) - 604800
timestamp_file = "timestamp"

# Try to read the Unix time from the timestamp file, use the default value if the file doesn't exist
try:
    with open(timestamp_file, "r") as file:
        content = file.read().strip()
        if not content:  # Check if the file is empty
            raise ValueError("Timestamp file is empty")
        input_unix_time = int(content)
except (FileNotFoundError, ValueError) as e:
    logging.warning(f"Using default_unix_time due to error: {e}")
    input_unix_time = default_unix_time

rss_url = "https://feeds.feedburner.com/AmazonWebServicesBlog"

feed = feedparser.parse(rss_url)
entries = []

for entry in feed.entries:
    if (
        int(datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %z").timestamp())
        > input_unix_time
    ):
        response = requests.get(entry.link)
        soup = BeautifulSoup(response.text, "html.parser")
        image_url = soup.find("meta", property="og:image").get("content")
        entry_dict = {
            "url": entry.link,
            "title": entry.title,
            "description": entry.description,
            "timestamp": int(
                datetime.strptime(
                    entry.published, "%a, %d %b %Y %H:%M:%S %z"
                ).timestamp()
            ),
            "image": image_url,
        }
        logging.info(entry_dict)
        entries.append(entry_dict)

# Bluesky init
now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

try:
    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": blue_login, "password": blue_password},
        timeout=10,
    )
    resp.raise_for_status()
    session = resp.json()
except requests.RequestException as e:
    logging.error(f"Failed to create BlueSky session. Error: {e}")
except json.JSONDecodeError as e:
    logging.error(f"Failed to decode BlueSky session response. Error: {e}")

logging.info(f"Logged into Bluesky.")

# Loop through the entries (old -> new) and post each link title as a card to BlueSky
for entry in entries:
    url = entry["url"]
    title = entry["title"]
    description = entry["description"]

    # Upload card image
    try:
        resp = requests.get(entry["image"])
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch card image. Error: {e}")
    # Resize the image to width 300 because Bluesky just doesn't like big pictures I guess
    img = Image.open(BytesIO(resp.content))
    width_percent = 300 / float(img.size[0])
    new_height = int((float(img.size[1]) * float(width_percent)))
    img = img.resize((300, new_height), Image.ANTIALIAS)
    img_bytes = BytesIO()
    img.save(img_bytes, format="PNG")
    blob_resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
        headers={
            "Content-Type": "image/png",
            "Authorization": "Bearer " + session["accessJwt"],
        },
        data=img_bytes.getvalue(),
        timeout=10,
    )
    blob_resp.raise_for_status()
    logging.info(f"Bluesky POST success.")
    thumb = blob_resp.json()["blob"]

    # 300 character limit
    if len(title) > 300:
        title = title[: max_title_length - 3] + "..."  # Truncate and add ellipsis

    post = {
        "$type": "app.bsky.feed.post",
        "text": "",
        "createdAt": now,
        "langs": ["en-US"],
        # Card
        "embed": {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": url,
                "title": title,
                "description": description,
                "thumb": thumb,
            },
        },
    }

    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": "Bearer " + session["accessJwt"]},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": post,
            },
            timeout=10,
        )
        logging.info(json.dumps(resp.json(), indent=2))
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to post to BlueSky. Error: {e}")
        continue
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode BlueSky post response. Error: {e}")
        continue

# Write the current Unix time to the timestamp file
try:
    with open(timestamp_file, "w") as file:
        file.write(str(int(time.time())))
    logging.info(f"Successfully wrote to {timestamp_file}")
except Exception as e:
    logging.error(f"Failed to write to {timestamp_file}. Error: {e}")

