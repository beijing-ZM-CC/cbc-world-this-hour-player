from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
HTTP_HEADERS = {
    "User-Agent": "CBC-Bilingual-Player/1.0 (+https://www.cbc.ca/radio/podcasts)",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


def parse_duration_seconds(raw: str | None) -> int:
    if not raw:
        return 0
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return nums[0] if nums else 0


def parse_pub_date(raw: str | None) -> tuple[str, float, str]:
    """Return (iso_utc, unix_ts, display_label)."""
    if not raw:
        now = datetime.now(timezone.utc)
        return now.isoformat(), now.timestamp(), now.strftime("%Y-%m-%d %H:%M UTC")
    try:
        dt = parsedate_to_datetime(raw.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz_match = re.search(r"\b(EST|EDT|CST|CDT|MST|MDT|PST|PDT|AST|ADT|NST|NDT|UTC|GMT)\b", raw.strip())
        tz_label = tz_match.group(1) if tz_match else (dt.tzname() or "UTC")
        display = dt.strftime(f"%Y-%m-%d %H:%M {tz_label}")
        return dt.astimezone(timezone.utc).isoformat(), dt.timestamp(), display
    except Exception:
        now = datetime.now(timezone.utc)
        return now.isoformat(), now.timestamp(), raw.strip()


def clean_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_episode_id(feed_key: str, guid: str, audio_url: str) -> str:
    seed = f"{feed_key}:{guid or audio_url}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{feed_key}-{digest}"


async def fetch_feed_episodes(feed: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=HTTP_HEADERS) as client:
        resp = await client.get(feed["url"])
        resp.raise_for_status()
        xml_bytes = resp.content

    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []

    episodes: list[dict[str, Any]] = []
    for item in channel.findall("item")[:limit]:
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.attrib.get("url"):
            continue

        audio_url = enclosure.attrib["url"].strip()
        guid = (item.findtext("guid") or "").strip() or audio_url
        title = (item.findtext("title") or feed["name"]).strip()
        desc = clean_html(item.findtext("description") or item.findtext(f"{ITUNES_NS}summary"))
        pub_raw = (item.findtext("pubDate") or "").strip()
        pub_iso, pub_ts, pub_display = parse_pub_date(pub_raw)
        dur_raw = item.findtext(f"{ITUNES_NS}duration")
        duration = parse_duration_seconds(dur_raw)

        # Make The World This Hour titles include the exact broadcast time so archived hours are unmistakable
        if feed["key"] == "twth":
            display_title = f"The World This Hour · {pub_display}"
        else:
            display_title = f"{title} ({pub_display[:10]})" if pub_display[:10] not in title else title

        ep_id = make_episode_id(feed["key"], guid, audio_url)
        episodes.append(
            {
                "id": ep_id,
                "feed_key": feed["key"],
                "feed_name": feed["name"],
                "guid": guid,
                "title": title,
                "display_title": display_title,
                "description": desc,
                "pub_date_raw": pub_raw,
                "pub_date_iso": pub_iso,
                "pub_ts": pub_ts,
                "pub_display": pub_display,
                "duration": duration,
                "remote_audio_url": audio_url,
            }
        )

    return episodes
