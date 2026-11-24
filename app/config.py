from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
SUBTITLE_DIR = DATA_DIR / "subtitles"
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = DATA_DIR / "episodes.json"

for _d in (DATA_DIR, AUDIO_DIR, SUBTITLE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Official CBC News RSS feeds
FEEDS = [
    {
        "key": "twth",
        "name": "The World This Hour",
        "label": "The World This Hour（每小时新闻 · 5分钟）",
        "url": "https://www.cbc.ca/podcasting/includes/hourlynews.xml",
        "max_items": 48,        # Keep up to 48 archived hourly episodes locally
        "auto_process": True,   # Automatically download & transcribe new hourly episodes
    },
    {
        "key": "wr",
        "name": "World Report",
        "label": "World Report（每日晨间新闻 · 10分钟）",
        "url": "https://www.cbc.ca/podcasting/includes/wr.xml",
        "max_items": 7,         # Latest 7 days, all with paragraphed bilingual subtitles
        "auto_process": False,  # Transcribe on demand locally; pre-generated in cloud Pages
    },
    {
        "key": "ywt",
        "name": "Your World Tonight",
        "label": "Your World Tonight（每日晚间新闻 · 30分钟）",
        "url": "https://www.cbc.ca/podcasting/includes/w6.xml",
        "max_items": 5,         # Latest 5 days, all with paragraphed bilingual subtitles
        "auto_process": False,  # Transcribe on demand locally; pre-generated in cloud Pages
    },
]

# Free local Whisper model settings
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "0"))  # 0 = auto

# Background sync interval (seconds): check every 15 minutes so hourly updates are caught promptly
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "900"))
