from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import FEEDS, STATIC_DIR
from app.feeds import fetch_feed_episodes
from app.paragrapher import upgrade_subtitles_with_paragraphs
from app.transcriber import SubtitleProcessor, _decode_audio_16k_mono, _normalize_segments, _translate_batch_en_to_zh

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_static")

HTTP_HEADERS = {"User-Agent": "CBC-Bilingual-Player-StaticSync/1.0"}

# Limits for static GitHub Pages artifact size (must stay safely under GitHub Pages' ~100 MB deploy cap)
AUDIO_ARCHIVE_LIMITS = {
    "twth": 12,  # Keep latest 12 archived hourly MP3s (~58 MB)
    "wr": 2,     # Keep latest 2 World Report MP3s (~19 MB)
    "ywt": 0,    # Stream 30-min Your World Tonight from CBC CDN while archiving its bilingual subtitles locally
}
MAX_AUDIO_TOTAL_BYTES = 85 * 1024 * 1024  # Hard cap: 85 MB total MP3s so Pages deploy never exceeds 100 MB
AUTO_TRANSCRIBE_TOP = {
    "twth": 48,  # Every archived hourly episode has full paragraphed bilingual subtitles
    "wr": 4,     # All 4 World Report episodes have full paragraphed bilingual subtitles
    "ywt": 2,    # All 2 Your World Tonight episodes have full paragraphed bilingual subtitles
}
MAX_REPAIR_LINES_PER_RUN = 360
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _download_file(client: httpx.Client, url: str, target: Path) -> bool:
    try:
        part = target.with_suffix(target.suffix + ".part")
        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return False
            with part.open("wb") as f:
                for chunk in resp.iter_bytes(65536):
                    if chunk:
                        f.write(chunk)
        part.replace(target)
        return target.exists() and target.stat().st_size > 100
    except Exception as exc:
        logger.warning("Download failed (%s): %s", url, exc)
        return False


def restore_from_previous_site(prev_site_url: str, data_dir: Path) -> dict[str, dict[str, Any]]:
    """Restore previously archived episodes, subtitles, and MP3s from the live GitHub Pages site."""
    base = prev_site_url.rstrip("/")
    episodes_map: dict[str, dict[str, Any]] = {}
    audio_dir = data_dir / "audio"
    sub_dir = data_dir / "subtitles"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sub_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0, follow_redirects=True, headers=HTTP_HEADERS) as client:
        try:
            r = client.get(f"{base}/data/episodes.json")
            if r.status_code != 200:
                logger.info("No previous site archive found at %s (HTTP %d).", base, r.status_code)
                return episodes_map
            payload = r.json()
            eps = payload if isinstance(payload, list) else payload.get("episodes", [])
            logger.info("Restoring %d archived episodes from %s", len(eps), base)
        except Exception as exc:
            logger.info("Could not read previous archive (%s): %s", base, exc)
            return episodes_map

        for ep in eps:
            ep_id = ep.get("id")
            if not ep_id:
                continue
            episodes_map[ep_id] = ep

            # Restore subtitle JSON if archived
            if ep.get("has_subtitles"):
                sub_file = sub_dir / f"{ep_id}.json"
                if not sub_file.exists():
                    ok = _download_file(client, f"{base}/data/subtitles/{ep_id}.json", sub_file)
                    if not ok:
                        ep["has_subtitles"] = False
                        ep.pop("static_subtitle_path", None)

            # Restore archived MP3 if present on previous Pages deployment
            if ep.get("static_audio_path"):
                audio_file = audio_dir / f"{ep_id}.mp3"
                if not audio_file.exists():
                    ok = _download_file(client, f"{base}/{ep['static_audio_path']}", audio_file)
                    if not ok:
                        ep.pop("static_audio_path", None)
                        ep["has_audio"] = False

    return episodes_map


def restore_from_local_cache(local_data: Path, out_data: Path) -> dict[str, dict[str, Any]]:
    episodes_map: dict[str, dict[str, Any]] = {}
    idx_file = local_data / "episodes.json"
    if not idx_file.exists():
        return episodes_map

    try:
        raw = json.loads(idx_file.read_text(encoding="utf-8"))
        eps = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    except Exception:
        return episodes_map

    (out_data / "audio").mkdir(parents=True, exist_ok=True)
    (out_data / "subtitles").mkdir(parents=True, exist_ok=True)

    for ep in eps:
        ep_id = ep.get("id")
        if not ep_id:
            continue
        ep_copy = dict(ep)
        src_sub = local_data / "subtitles" / f"{ep_id}.json"
        if src_sub.exists():
            shutil.copy2(src_sub, out_data / "subtitles" / f"{ep_id}.json")
            ep_copy["has_subtitles"] = True
            ep_copy["static_subtitle_path"] = f"data/subtitles/{ep_id}.json"
        src_aud = local_data / "audio" / f"{ep_id}.mp3"
        if src_aud.exists():
            shutil.copy2(src_aud, out_data / "audio" / f"{ep_id}.mp3")
            ep_copy["has_audio"] = True
            ep_copy["static_audio_path"] = f"data/audio/{ep_id}.mp3"
        episodes_map[ep_id] = ep_copy

    return episodes_map


async def build_static_site(out_dir: Path, prev_site_url: str | None, seed_local: bool) -> None:
    out_data = out_dir / "data"
    audio_dir = out_data / "audio"
    sub_dir = out_data / "subtitles"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sub_dir.mkdir(parents=True, exist_ok=True)

    episodes_map: dict[str, dict[str, Any]] = {}
    if seed_local and (ROOT / "data").exists():
        episodes_map.update(restore_from_local_cache(ROOT / "data", out_data))
    if prev_site_url:
        restored = restore_from_previous_site(prev_site_url, out_data)
        for k, v in restored.items():
            episodes_map.setdefault(k, v)

    # Fetch live CBC RSS feeds
    for feed in FEEDS:
        try:
            fetch_limit = 5 if feed["key"] == "twth" else feed["max_items"]
            incoming = await fetch_feed_episodes(feed, limit=fetch_limit)
            logger.info("Fetched %d items from %s", len(incoming), feed["name"])
            for item in incoming:
                ep_id = item["id"]
                if ep_id not in episodes_map:
                    episodes_map[ep_id] = {
                        **item,
                        "status": "idle",
                        "progress": 0,
                        "has_audio": False,
                        "has_subtitles": False,
                        "subtitle_count": 0,
                    }
                else:
                    for field in ("title", "display_title", "description", "remote_audio_url", "pub_display", "pub_ts", "pub_date_iso"):
                        if item.get(field):
                            episodes_map[ep_id][field] = item[field]
        except Exception as exc:
            logger.warning("Failed fetching %s: %s", feed["name"], exc)

    # Sort and prune episodes per feed
    feed_order = {f["key"]: i for i, f in enumerate(FEEDS)}
    kept_episodes: list[dict[str, Any]] = []
    for feed in FEEDS:
        key = feed["key"]
        eps = [e for e in episodes_map.values() if e.get("feed_key") == key]
        eps.sort(key=lambda e: float(e.get("pub_ts", 0.0)), reverse=True)
        eps = eps[: feed["max_items"]]
        kept_episodes.extend(eps)

    # Transcribe & archive top episodes per feed that are missing bilingual subtitles
    proc = SubtitleProcessor()
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=HTTP_HEADERS) as client:
        for feed in FEEDS:
            key = feed["key"]
            top_n = AUTO_TRANSCRIBE_TOP.get(key, 0)
            feed_eps = [e for e in kept_episodes if e.get("feed_key") == key]
            audio_cap = AUDIO_ARCHIVE_LIMITS.get(key, 0)
            for idx, ep in enumerate(feed_eps[:top_n]):
                ep_id = ep["id"]
                sub_file = sub_dir / f"{ep_id}.json"
                aud_file = audio_dir / f"{ep_id}.mp3"

                need_sub = not sub_file.exists() or sub_file.stat().st_size < 20
                need_audio = idx < audio_cap
                if not need_sub and not need_audio:
                    continue

                if not aud_file.exists() or aud_file.stat().st_size < 1000:
                    logger.info("Downloading audio for %s (%s)...", ep_id, ep.get("display_title"))
                    ok = _download_file(client, ep["remote_audio_url"], aud_file)
                    if not ok:
                        logger.warning("Skipping %s: could not download MP3", ep_id)
                        continue
                ep["has_audio"] = True
                ep["static_audio_path"] = f"data/audio/{ep_id}.mp3"

                if need_sub:
                    logger.info("Transcribing & translating %s...", ep_id)
                    model = proc._get_model()
                    audio_array = _decode_audio_16k_mono(aud_file)
                    segs_iter, info = model.transcribe(
                        audio_array,
                        language="en",
                        beam_size=2,
                        initial_prompt="CBC News: The World This Hour. World Report. Your World Tonight. Canada, Ottawa, Toronto, Vancouver, British Columbia.",
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 450},
                        condition_on_previous_text=True,
                    )
                    total_dur = float(getattr(info, "duration", 0.0) or ep.get("duration") or 0.0)
                    raw_segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segs_iter]
                    subtitles = _normalize_segments(raw_segs)
                    zh_list = _translate_batch_en_to_zh([s["en"] for s in subtitles])
                    for sub, zh in zip(subtitles, zh_list):
                        sub["zh"] = zh

                    sub_file.write_text(json.dumps(subtitles, ensure_ascii=False, indent=2), encoding="utf-8")
                    ep["has_subtitles"] = True
                    ep["static_subtitle_path"] = f"data/subtitles/{ep_id}.json"
                    ep["subtitle_count"] = len(subtitles)
                    ep["status"] = "ready"
                    ep["progress"] = 100
                    if total_dur > 0:
                        ep["duration"] = int(round(total_dur))
                    logger.info("Generated %d bilingual lines for %s", len(subtitles), ep_id)

    # Enforce per-feed MP3 archive cap AND global 85 MB budget, plus auto-repair any missing Chinese translations
    valid_audio_ids: set[str] = set()
    valid_sub_ids: set[str] = set()
    total_audio_bytes = 0
    repaired_lines_total = 0
    for feed in FEEDS:
        key = feed["key"]
        feed_eps = [e for e in kept_episodes if e.get("feed_key") == key]
        audio_cap = AUDIO_ARCHIVE_LIMITS.get(key, 0)
        for idx, ep in enumerate(feed_eps):
            ep_id = ep["id"]
            sub_path = sub_dir / f"{ep_id}.json"
            if sub_path.exists():
                try:
                    existing_subs = json.loads(sub_path.read_text(encoding="utf-8"))
                    changed = False
                    if isinstance(existing_subs, list) and existing_subs:
                        if not all("paragraph" in s for s in existing_subs):
                            existing_subs = upgrade_subtitles_with_paragraphs(existing_subs)
                            changed = True
                        # Auto-repair any lines that fell back to untranslated English
                        if repaired_lines_total < MAX_REPAIR_LINES_PER_RUN:
                            missing_idxs = [
                                i for i, s in enumerate(existing_subs)
                                if (s.get("en") or "").strip() and not CJK_RE.search(s.get("zh") or "")
                            ]
                            if missing_idxs:
                                budget = MAX_REPAIR_LINES_PER_RUN - repaired_lines_total
                                to_fix = missing_idxs[:budget]
                                logger.info("Repairing %d untranslated Chinese lines in %s...", len(to_fix), ep_id)
                                fixed_zh = _translate_batch_en_to_zh([existing_subs[i]["en"] for i in to_fix])
                                for i_pos, zh_val in zip(to_fix, fixed_zh):
                                    if CJK_RE.search(zh_val or ""):
                                        existing_subs[i_pos]["zh"] = zh_val
                                        changed = True
                                repaired_lines_total += len(to_fix)
                        if changed:
                            sub_path.write_text(json.dumps(existing_subs, ensure_ascii=False, indent=2), encoding="utf-8")
                            ep["subtitle_count"] = len(existing_subs)
                except Exception as exc:
                    logger.warning("Failed upgrading/repairing subtitles for %s: %s", ep_id, exc)
                valid_sub_ids.add(ep_id)
                ep["has_subtitles"] = True
                ep["static_subtitle_path"] = f"data/subtitles/{ep_id}.json"
                ep["status"] = "ready"
            else:
                ep["has_subtitles"] = False
                ep.pop("static_subtitle_path", None)

            aud_path = audio_dir / f"{ep_id}.mp3"
            aud_size = aud_path.stat().st_size if aud_path.exists() else 0
            if idx < audio_cap and aud_size > 1000 and (total_audio_bytes + aud_size) <= MAX_AUDIO_TOTAL_BYTES:
                valid_audio_ids.add(ep_id)
                total_audio_bytes += aud_size
                ep["has_audio"] = True
                ep["static_audio_path"] = f"data/audio/{ep_id}.mp3"
            else:
                ep["has_audio"] = False
                ep.pop("static_audio_path", None)

    for f in audio_dir.glob("*.mp3"):
        if f.stem not in valid_audio_ids:
            f.unlink(missing_ok=True)
    for f in sub_dir.glob("*.json"):
        if f.stem not in valid_sub_ids:
            f.unlink(missing_ok=True)
    logger.info("Archived MP3 payload size: %.1f MB (%d files)", total_audio_bytes / (1024 * 1024), len(valid_audio_ids))

    # Sort final list: The World This Hour -> World Report -> Your World Tonight, newest first
    kept_episodes.sort(key=lambda e: (feed_order.get(e.get("feed_key", ""), 99), -float(e.get("pub_ts", 0.0))))

    manifest_payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "episodes": kept_episodes,
    }
    (out_data / "episodes.json").write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Copy PWA frontend assets into dist/
    for item in STATIC_DIR.iterdir():
        dest = out_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    logger.info("Static site built at %s (%d episodes, %d MP3s archived, %d subtitle files).",
                out_dir, len(kept_episodes), len(valid_audio_ids), len(valid_sub_ids))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static PWA bundle with CBC bilingual subtitles.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--prev-site-url", type=str, default="")
    parser.add_argument("--seed-local", action="store_true")
    args = parser.parse_args()
    asyncio.run(build_static_site(args.out_dir, args.prev_site_url or None, args.seed_local))


if __name__ == "__main__":
    main()
