from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from pathlib import Path
from typing import Any

from .config import AUDIO_DIR, FEEDS, INDEX_FILE, SUBTITLE_DIR


def format_srt_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours = ms_total // 3_600_000
    rem = ms_total % 3_600_000
    minutes = rem // 60_000
    rem %= 60_000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def safe_filename_slug(episode: dict[str, Any]) -> str:
    base = f"CBC_{episode.get('feed_name', 'news')}_{episode.get('pub_display', episode['id'])}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return slug[:90] or episode["id"]


def build_srt(subtitles: list[dict[str, Any]], mode: str = "en") -> str:
    """mode: 'en', 'zh', or 'bilingual'."""
    blocks: list[str] = []
    for idx, item in enumerate(subtitles, start=1):
        start = format_srt_timestamp(float(item.get("start", 0.0)))
        end = format_srt_timestamp(float(item.get("end", 0.0)))
        en = (item.get("en") or "").strip()
        zh = (item.get("zh") or "").strip()
        if mode == "en":
            body = en
        elif mode == "zh":
            body = zh or en
        else:
            body = f"{en}\n{zh}" if zh else en
        blocks.append(f"{idx}\n{start} --> {end}\n{body}\n")
    return "\n".join(blocks)


def build_bilingual_txt(episode: dict[str, Any], subtitles: list[dict[str, Any]]) -> str:
    lines = [
        f"Title: {episode.get('display_title', episode.get('title', ''))}",
        f"Program: {episode.get('feed_name', '')}",
        f"Published: {episode.get('pub_display', '')}",
        "=" * 64,
        "",
    ]
    for item in subtitles:
        ts = f"[{format_mmss(float(item.get('start', 0.0)))} - {format_mmss(float(item.get('end', 0.0)))}]"
        lines.append(ts)
        lines.append(item.get("en", "").strip())
        if item.get("zh"):
            lines.append(item.get("zh", "").strip())
        lines.append("")
    return "\n".join(lines)


class EpisodeStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._episodes: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not INDEX_FILE.exists():
                self._episodes = {}
                return
            try:
                raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._episodes = raw
                elif isinstance(raw, list):
                    self._episodes = {ep["id"]: ep for ep in raw if "id" in ep}
            except Exception:
                self._episodes = {}

            # Reconcile transient states left over from a previous crash/restart
            changed = False
            for ep in self._episodes.values():
                sub_file = self.subtitle_path(ep["id"])
                audio_file = self.audio_path(ep["id"])
                ep["has_audio"] = audio_file.exists() and audio_file.stat().st_size > 1000
                ep["has_subtitles"] = sub_file.exists() and sub_file.stat().st_size > 10
                if ep["has_subtitles"]:
                    if ep.get("status") != "ready":
                        ep["status"] = "ready"
                        ep["progress"] = 100
                        ep["error"] = None
                        changed = True
                elif ep.get("status") in ("queued", "downloading", "transcribing", "translating"):
                    ep["status"] = "idle"
                    ep["progress"] = 0
                    ep["status_message"] = "选择后将自动生成中英字幕"
                    changed = True
            if changed:
                self._save()

    def _save(self) -> None:
        tmp = INDEX_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._episodes, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(INDEX_FILE)

    def audio_path(self, ep_id: str) -> Path:
        return AUDIO_DIR / f"{ep_id}.mp3"

    def subtitle_path(self, ep_id: str) -> Path:
        return SUBTITLE_DIR / f"{ep_id}.json"

    def upsert_feed_episodes(self, feed_key: str, incoming: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
        """Merge fetched RSS items while preserving archived episodes up to max_items."""
        newly_added: list[dict[str, Any]] = []
        with self._lock:
            for item in incoming:
                ep_id = item["id"]
                existing = self._episodes.get(ep_id)
                if existing is None:
                    audio_exists = self.audio_path(ep_id).exists()
                    sub_exists = self.subtitle_path(ep_id).exists()
                    record = {
                        **item,
                        "status": "ready" if sub_exists else "idle",
                        "progress": 100 if sub_exists else 0,
                        "status_message": "中英字幕已就绪" if sub_exists else "待生成字幕",
                        "error": None,
                        "has_audio": audio_exists,
                        "has_subtitles": sub_exists,
                        "subtitle_count": 0,
                    }
                    self._episodes[ep_id] = record
                    newly_added.append(record)
                else:
                    # Keep local archive status and refresh remote URL/metadata
                    for k in ("title", "display_title", "description", "remote_audio_url", "pub_display", "pub_ts", "pub_date_iso"):
                        if item.get(k):
                            existing[k] = item[k]
                    if item.get("duration") and not existing.get("duration"):
                        existing["duration"] = item["duration"]

            # Prune oldest beyond max_items for this feed
            feed_eps = [ep for ep in self._episodes.values() if ep.get("feed_key") == feed_key]
            feed_eps.sort(key=lambda e: float(e.get("pub_ts", 0.0)), reverse=True)
            for stale in feed_eps[max_items:]:
                stale_id = stale["id"]
                self._episodes.pop(stale_id, None)
                for p in (self.audio_path(stale_id), self.subtitle_path(stale_id)):
                    if p.exists():
                        try:
                            p.unlink()
                        except OSError:
                            pass

            self._save()
        return newly_added

    def list_episodes(self, feed_key: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            eps = list(self._episodes.values())
            if feed_key:
                eps = [e for e in eps if e.get("feed_key") == feed_key]
            feed_order = {f["key"]: i for i, f in enumerate(FEEDS)}
            eps.sort(key=lambda e: (feed_order.get(e.get("feed_key", ""), 99), -float(e.get("pub_ts", 0.0))))
            return [dict(e) for e in eps]

    def get_episode(self, ep_id: str) -> dict[str, Any] | None:
        with self._lock:
            ep = self._episodes.get(ep_id)
            return dict(ep) if ep else None

    def update_episode(self, ep_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            ep = self._episodes.get(ep_id)
            if ep is None:
                return None
            ep.update(fields)
            self._save()
            return dict(ep)

    def save_subtitles(self, ep_id: str, subtitles: list[dict[str, Any]], duration: float | None = None) -> None:
        with self._lock:
            p = self.subtitle_path(ep_id)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(subtitles, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
            ep = self._episodes.get(ep_id)
            if ep is not None:
                ep["has_subtitles"] = True
                ep["subtitle_count"] = len(subtitles)
                ep["status"] = "ready"
                ep["progress"] = 100
                ep["status_message"] = f"已生成 {len(subtitles)} 句双语字幕"
                ep["error"] = None
                if duration and duration > 0:
                    ep["duration"] = int(round(duration))
                self._save()

    def load_subtitles(self, ep_id: str) -> list[dict[str, Any]]:
        p = self.subtitle_path(ep_id)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def build_bundle_zip(self, ep_id: str) -> tuple[bytes, str] | None:
        ep = self.get_episode(ep_id)
        if not ep:
            return None
        audio_file = self.audio_path(ep_id)
        subtitles = self.load_subtitles(ep_id)
        slug = safe_filename_slug(ep)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            if audio_file.exists():
                zf.write(audio_file, arcname=f"{slug}.mp3")
            if subtitles:
                zf.writestr(f"{slug}_en.srt", build_srt(subtitles, "en").encode("utf-8-sig"))
                zf.writestr(f"{slug}_zh.srt", build_srt(subtitles, "zh").encode("utf-8-sig"))
                zf.writestr(f"{slug}_bilingual.srt", build_srt(subtitles, "bilingual").encode("utf-8-sig"))
                zf.writestr(f"{slug}_bilingual.txt", build_bilingual_txt(ep, subtitles).encode("utf-8-sig"))
        return buf.getvalue(), f"{slug}.zip"


store = EpisodeStore()
