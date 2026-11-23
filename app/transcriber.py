from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import av
import httpx
import numpy as np
from faster_whisper import WhisperModel

from .config import WHISPER_COMPUTE_TYPE, WHISPER_CPU_THREADS, WHISPER_MODEL
from .storage import store

logger = logging.getLogger("cbc_player.transcriber")

HTTP_HEADERS = {
    "User-Agent": "CBC-Bilingual-Player/1.0 (+https://www.cbc.ca/radio/podcasts)",
}


def _decode_audio_16k_mono(audio_path: Path) -> np.ndarray:
    """Decode audio file to 16kHz mono float32 numpy array compatible with any PyAV version."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    with av.open(str(audio_path), mode="r") as container:
        audio_stream = next((s for s in container.streams if s.type == "audio"), None)
        if audio_stream is None:
            raise RuntimeError("No audio stream found in downloaded file")
        for frame in container.decode(audio_stream):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
        for resampled in resampler.resample(None):
            chunks.append(resampled.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    pcm16 = np.concatenate(chunks)
    return pcm16.astype(np.float32) / 32768.0


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _normalize_segments(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge tiny fragments and ensure crisp readable sentence-level subtitle blocks."""
    merged: list[dict[str, Any]] = []
    for seg in raw_segments:
        txt = _clean_text(seg["text"])
        if not txt:
            continue
        start = round(float(seg["start"]), 2)
        end = round(float(seg["end"]), 2)
        if end <= start:
            end = round(start + 0.5, 2)

        if merged:
            prev = merged[-1]
            prev_txt = prev["en"]
            gap = start - prev["end"]
            prev_dur = prev["end"] - prev["start"]
            # Merge short non-terminated fragment into previous line
            if (
                not re.search(r"[.!?\"']$", prev_txt)
                and gap < 0.75
                and (prev_dur + (end - start)) <= 10.5
                and len(prev_txt) + len(txt) < 155
            ):
                prev["en"] = f"{prev_txt} {txt}"
                prev["end"] = end
                continue

        merged.append({"start": start, "end": end, "en": txt, "zh": ""})

    for idx, item in enumerate(merged):
        item["id"] = idx
    return merged


def _google_gtx_translate(client: httpx.Client, text: str) -> str:
    resp = client.post(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"},
        data={"q": text},
        timeout=20.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    return "".join(part[0] for part in payload[0] if part and part[0]).strip()


def _translate_batch_en_to_zh(texts: list[str]) -> list[str]:
    """Translate English sentences into Simplified Chinese with exact 1-to-1 alignment."""
    if not texts:
        return []

    results: list[str] = []
    batch_size = 15

    with httpx.Client(timeout=20.0, headers=HTTP_HEADERS) as client:
        for i in range(0, len(texts), batch_size):
            chunk = [t.replace("\n", " ").strip() for t in texts[i : i + batch_size]]
            joined = "\n".join(chunk)
            translated_chunk: list[str] | None = None

            if len(joined) <= 4500:
                for attempt in range(2):
                    try:
                        out = _google_gtx_translate(client, joined)
                        lines = [line.strip() for line in out.splitlines() if line.strip() != ""]
                        if len(lines) == len(chunk):
                            translated_chunk = lines
                            break
                    except Exception as exc:
                        logger.warning("Batch GTX translate attempt %d failed: %s", attempt + 1, exc)
                        time.sleep(0.5)

            if translated_chunk is None:
                translated_chunk = []
                for line in chunk:
                    translated_line = None
                    try:
                        translated_line = _google_gtx_translate(client, line)
                    except Exception as exc:
                        logger.warning("Single GTX translate failed, trying MyMemory: %s", exc)
                        try:
                            mm = client.get(
                                "https://api.mymemory.translated.net/get",
                                params={"q": line[:480], "langpair": "en|zh-CN"},
                                timeout=12.0,
                            )
                            if mm.status_code == 200:
                                translated_line = (mm.json().get("responseData", {}).get("translatedText") or "").strip()
                        except Exception:
                            pass
                    translated_chunk.append(translated_line or line)
                    time.sleep(0.12)

            results.extend(translated_chunk)
            time.sleep(0.25)

    return results


class SubtitleProcessor:
    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-worker")
        self._inflight_lock = threading.Lock()
        self._inflight: set[str] = set()

    def _get_model(self) -> WhisperModel:
        with self._model_lock:
            if self._model is None:
                logger.info("Loading faster-whisper model '%s' (%s)...", WHISPER_MODEL, WHISPER_COMPUTE_TYPE)
                kwargs: dict[str, Any] = {
                    "device": "cpu",
                    "compute_type": WHISPER_COMPUTE_TYPE,
                }
                if WHISPER_CPU_THREADS > 0:
                    kwargs["cpu_threads"] = WHISPER_CPU_THREADS
                self._model = WhisperModel(WHISPER_MODEL, **kwargs)
                logger.info("faster-whisper model loaded.")
            return self._model

    def download_audio_sync(self, ep_id: str) -> Path:
        ep = store.get_episode(ep_id)
        if not ep:
            raise ValueError(f"Episode not found: {ep_id}")

        target = store.audio_path(ep_id)
        if target.exists() and target.stat().st_size > 1000:
            if not ep.get("has_audio"):
                store.update_episode(ep_id, has_audio=True)
            return target

        url = ep["remote_audio_url"]
        part = target.with_suffix(".mp3.part")
        with httpx.Client(timeout=60.0, follow_redirects=True, headers=HTTP_HEADERS) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with part.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
        part.replace(target)
        store.update_episode(ep_id, has_audio=True)
        return target

    def _process_episode_blocking(self, ep_id: str) -> None:
        try:
            ep = store.get_episode(ep_id)
            if not ep:
                return
            if store.subtitle_path(ep_id).exists() and store.audio_path(ep_id).exists():
                store.update_episode(ep_id, status="ready", progress=100, has_audio=True, has_subtitles=True)
                return

            store.update_episode(
                ep_id,
                status="downloading",
                progress=5,
                status_message="正在下载 CBC 音频文件...",
                error=None,
            )
            audio_path = self.download_audio_sync(ep_id)

            store.update_episode(
                ep_id,
                status="transcribing",
                progress=12,
                status_message="正在加载免费语音识别模型并转写英文字幕...",
            )
            model = self._get_model()
            audio_array = _decode_audio_16k_mono(audio_path)
            segments_iter, info = model.transcribe(
                audio_array,
                language="en",
                beam_size=2,
                initial_prompt="CBC News: The World This Hour. World Report. Your World Tonight. Canada, Ottawa, Toronto, Vancouver, British Columbia.",
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 450},
                condition_on_previous_text=True,
            )
            total_dur = float(getattr(info, "duration", 0.0) or ep.get("duration") or 300.0)
            if total_dur > 0:
                store.update_episode(ep_id, duration=int(round(total_dur)))

            raw_segments: list[dict[str, Any]] = []
            last_update = 0.0
            for seg in segments_iter:
                raw_segments.append({"start": seg.start, "end": seg.end, "text": seg.text})
                now = time.monotonic()
                if now - last_update >= 0.8 and total_dur > 0:
                    pct = 12 + int(min(1.0, seg.end / total_dur) * 68)
                    store.update_episode(
                        ep_id,
                        status="transcribing",
                        progress=pct,
                        status_message=f"正在识别英文字幕 ({pct}%)...",
                    )
                    last_update = now

            subtitles = _normalize_segments(raw_segments)
            if not subtitles:
                raise RuntimeError("未能从音频中识别出有效语音内容")

            store.update_episode(
                ep_id,
                status="translating",
                progress=84,
                status_message=f"正在翻译 {len(subtitles)} 句中文字幕...",
            )
            zh_list = _translate_batch_en_to_zh([s["en"] for s in subtitles])
            for sub, zh in zip(subtitles, zh_list):
                sub["zh"] = zh

            store.save_subtitles(ep_id, subtitles, duration=total_dur)
            logger.info("Episode %s ready: %d bilingual lines.", ep_id, len(subtitles))
        except Exception as exc:
            logger.exception("Failed processing episode %s", ep_id)
            store.update_episode(
                ep_id,
                status="error",
                progress=0,
                status_message="字幕生成失败，可点击重试",
                error=str(exc),
            )
        finally:
            with self._inflight_lock:
                self._inflight.discard(ep_id)

    def enqueue(self, ep_id: str) -> bool:
        ep = store.get_episode(ep_id)
        if not ep:
            return False
        if ep.get("has_subtitles") and ep.get("has_audio") and ep.get("status") == "ready":
            return False
        with self._inflight_lock:
            if ep_id in self._inflight:
                return False
            self._inflight.add(ep_id)

        store.update_episode(
            ep_id,
            status="queued",
            progress=2,
            status_message="已加入字幕生成队列...",
            error=None,
        )
        self._executor.submit(self._process_episode_blocking, ep_id)
        return True

    async def ensure_audio_async(self, ep_id: str) -> Path:
        target = store.audio_path(ep_id)
        if target.exists() and target.stat().st_size > 1000:
            return target
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.download_audio_sync, ep_id)


processor = SubtitleProcessor()
