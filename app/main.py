from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import FEEDS, STATIC_DIR, SYNC_INTERVAL_SECONDS
from .feeds import fetch_feed_episodes
from .storage import build_bilingual_txt, build_srt, safe_filename_slug, store
from .transcriber import processor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cbc_player.main")

_last_sync_iso: str | None = None
_sync_lock = asyncio.Lock()


async def sync_all_feeds(auto_process_latest: bool = True) -> dict:
    global _last_sync_iso
    async with _sync_lock:
        added_total = 0
        errors: list[str] = []

        for feed in FEEDS:
            try:
                fetch_limit = 5 if feed["key"] == "twth" else feed["max_items"]
                items = await fetch_feed_episodes(feed, limit=fetch_limit)
                newly_added = store.upsert_feed_episodes(feed["key"], items, max_items=feed["max_items"])
                added_total += len(newly_added)
                logger.info("Feed %s synced: %d fetched, %d new.", feed["key"], len(items), len(newly_added))

                if auto_process_latest and feed.get("auto_process"):
                    # Always ensure the latest The World This Hour episode is processed & archived
                    twth_eps = store.list_episodes(feed_key=feed["key"])
                    if twth_eps:
                        latest = twth_eps[0]
                        if not latest.get("has_subtitles") or not latest.get("has_audio"):
                            processor.enqueue(latest["id"])
            except Exception as exc:
                logger.warning("Failed syncing feed %s: %s", feed["key"], exc)
                errors.append(f"{feed['name']}: {exc}")

        _last_sync_iso = datetime.now(timezone.utc).isoformat()
        return {
            "synced_at": _last_sync_iso,
            "new_episodes": added_total,
            "errors": errors,
        }


async def _background_sync_loop() -> None:
    while True:
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
        try:
            await sync_all_feeds(auto_process_latest=True)
        except Exception as exc:
            logger.warning("Background sync failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off initial sync without blocking server startup
    init_task = asyncio.create_task(sync_all_feeds(auto_process_latest=True))
    bg_task = asyncio.create_task(_background_sync_loop())
    try:
        yield
    finally:
        init_task.cancel()
        bg_task.cancel()


app = FastAPI(title="CBC Radio Bilingual Subtitle Player", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
    quoted = quote(filename)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"


@app.get("/api/health")
async def health():
    return {"ok": True, "last_sync": _last_sync_iso}


@app.get("/api/feeds")
async def get_feeds():
    return {
        "feeds": [
            {
                "key": f["key"],
                "name": f["name"],
                "label": f["label"],
                "auto_process": f["auto_process"],
            }
            for f in FEEDS
        ],
        "last_sync": _last_sync_iso,
    }


@app.get("/api/episodes")
async def list_episodes(feed: str | None = Query(default=None)):
    return {
        "episodes": store.list_episodes(feed_key=feed),
        "last_sync": _last_sync_iso,
    }


@app.post("/api/sync")
async def trigger_sync():
    result = await sync_all_feeds(auto_process_latest=True)
    return {
        **result,
        "episodes": store.list_episodes(),
    }


@app.get("/api/episodes/{ep_id}")
async def get_episode_detail(ep_id: str, process: bool = Query(default=True)):
    ep = store.get_episode(ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    if process and (not ep.get("has_subtitles") or not ep.get("has_audio")) and ep.get("status") in ("idle", "error"):
        processor.enqueue(ep_id)
        ep = store.get_episode(ep_id) or ep

    subtitles = store.load_subtitles(ep_id) if ep.get("has_subtitles") else []
    return {
        "episode": ep,
        "subtitles": subtitles,
    }


@app.post("/api/episodes/{ep_id}/process")
async def force_process_episode(ep_id: str):
    ep = store.get_episode(ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    processor.enqueue(ep_id)
    return {"episode": store.get_episode(ep_id)}


@app.get("/api/episodes/{ep_id}/audio")
async def stream_episode_audio(ep_id: str):
    ep = store.get_episode(ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    try:
        audio_path = await processor.ensure_audio_async(ep_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch CBC audio: {exc}") from exc

    return FileResponse(
        path=audio_path,
        media_type="audio/mpeg",
        filename=f"{safe_filename_slug(ep)}.mp3",
    )


@app.get("/api/episodes/{ep_id}/download")
async def download_episode_asset(
    ep_id: str,
    kind: str = Query(default="zip", pattern="^(zip|audio|srt_en|srt_zh|srt_bilingual|txt)$"),
):
    ep = store.get_episode(ep_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    slug = safe_filename_slug(ep)

    if kind == "audio":
        audio_path = await processor.ensure_audio_async(ep_id)
        return FileResponse(
            path=audio_path,
            media_type="audio/mpeg",
            headers={"Content-Disposition": _content_disposition(f"{slug}.mp3")},
        )

    subtitles = store.load_subtitles(ep_id)
    if kind in ("srt_en", "srt_zh", "srt_bilingual", "txt") and not subtitles:
        raise HTTPException(status_code=409, detail="该期字幕尚未生成完成，请稍候片刻再下载")

    if kind == "srt_en":
        content = build_srt(subtitles, "en").encode("utf-8-sig")
        return Response(
            content=content,
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _content_disposition(f"{slug}_en.srt")},
        )
    if kind == "srt_zh":
        content = build_srt(subtitles, "zh").encode("utf-8-sig")
        return Response(
            content=content,
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _content_disposition(f"{slug}_zh.srt")},
        )
    if kind == "srt_bilingual":
        content = build_srt(subtitles, "bilingual").encode("utf-8-sig")
        return Response(
            content=content,
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _content_disposition(f"{slug}_bilingual.srt")},
        )
    if kind == "txt":
        content = build_bilingual_txt(ep, subtitles).encode("utf-8-sig")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": _content_disposition(f"{slug}_bilingual.txt")},
        )

    # Default: bundle zip containing MP3 + EN/ZH/Bilingual SRT + TXT
    await processor.ensure_audio_async(ep_id)
    bundle = store.build_bundle_zip(ep_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Episode not found")
    data, filename = bundle
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/icons", StaticFiles(directory=str(STATIC_DIR / "icons")), name="icons")


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/index.html")
async def serve_index_html():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/styles.css")
async def serve_styles():
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
async def serve_app_js():
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def serve_sw():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")
