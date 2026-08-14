"""
Kairozen Song Search Bot
=========================
ស្វែងរក និងទាញយកចម្រៀងតាមចំណងជើង តាមរយៈ Telegram

របៀបប្រើ:
  /start          -> ចាប់ផ្តើម
  វាយចំណងជើងចម្រៀង -> Bot នឹងស្វែងរក 5 លទ្ធផលពី YouTube Music
                        ចុចជ្រើសរើសបទដែលចង់បាន -> Bot ផ្ញើជា audio file

Environment Variables (កំណត់នៅលើ Render):
  BOT_TOKEN         -> Token ពី @BotFather
  YTDLP_COOKIES_FILE -> (ស្រេចចិត្ត) path ទៅ cookies.txt សម្រាប់ជួយការទាញយក
  DATA_DIR          -> path ទៅ Persistent Disk (Render) សម្រាប់ទុកទិន្នន័យមិនឲ្យបាត់ពេល redeploy
                       ដូចជា /data (មើល render.yaml)
  PORT              -> (Render ផ្តល់ជូនស្វ័យប្រវត្តិ)

ស្ថាបត្យកម្ម ការពារការចាប់ (anti-block):
  - SEARCH ប្រើ ytmusicapi (មិនត្រូវការ API Key, unauthenticated public search)
  - DOWNLOAD ប្រើ yt-dlp ជាមួយ android player client + cookies (ស្រេចចិត្ត) ដើម្បីកាត់បន្ថយហានិភ័យ

Dependencies (requirements.txt):
  pyTelegramBotAPI
  yt-dlp
  flask
  ytmusicapi
"""

import os
import logging
import tempfile
import threading
import time
from pathlib import Path

import telebot
from telebot import types
from flask import Flask
from ytmusicapi import YTMusic
import yt_dlp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("❌ សូមកំណត់ Environment Variable ឈ្មោះ BOT_TOKEN ជាមុនសិន")

# Cookies file សម្រាប់ yt-dlp download (ជៀសវាងការចាប់ពេលទាញយក) - ស្រេចចិត្ត
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "")  # e.g. /etc/secrets/cookies.txt

MAX_RESULTS = 5          # ចំនួនលទ្ធផលស្វែងរកបង្ហាញ
MAX_DURATION_SEC = 1200  # កំណត់រយៈពេលអតិបរមា ២០នាទី (ការពារ file ធំពេក)
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "kairozen_song_bot"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Persistent data (មិនបាត់ទិន្នន័យពេល redeploy/update)
# DATA_DIR ត្រូវភ្ជាប់ទៅ Render Persistent Disk (មើល render.yaml / README)
# បើគ្មាន Persistent Disk, DATA_DIR និងខ្លឹមសាររបស់វានឹងបាត់រាល់ពេល redeploy
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE = DATA_DIR / "stats.json"
STATS_LOCK = threading.Lock()


def load_stats() -> dict:
    if STATS_FILE.exists():
        try:
            import json
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("stats.json corrupted, starting fresh")
    return {"total_searches": 0, "total_downloads": 0, "users": {}}


def save_stats(stats: dict):
    import json
    tmp = STATS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATS_FILE)  # atomic write ការពារ corrupt file


def record_event(user_id: int, kind: str):
    """kind: 'search' ឬ 'download' - រក្សាទុកជា JSON លើ persistent disk"""
    with STATS_LOCK:
        stats = load_stats()
        stats[f"total_{kind}s"] = stats.get(f"total_{kind}s", 0) + 1
        uid = str(user_id)
        user_stat = stats["users"].setdefault(uid, {"searches": 0, "downloads": 0})
        user_stat[f"{kind}s"] += 1
        save_stats(stats)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("song_search_bot")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# YTMusic() ដោយគ្មាន auth file -> public unauthenticated search (គ្មានត្រូវការ Key)
ytmusic = YTMusic()

# in-memory cache: {search_id: [ {id, title, duration, uploader}, ... ]}
SEARCH_CACHE: dict[str, list[dict]] = {}
CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def format_duration(seconds) -> str:
    if not seconds:
        return "?"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _duration_to_seconds(duration_str) -> int:
    """ytmusicapi ផ្តល់ duration ជា 'M:SS' ឬ 'H:MM:SS' string -> បំប្លែងទៅវិនាទី"""
    if not duration_str:
        return 0
    parts = str(duration_str).split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def search_youtube(query: str, limit: int = MAX_RESULTS) -> list[dict]:
    """ស្វែងរកបទចម្រៀងតាមចំណងជើងតាមរយៈ ytmusicapi (public search, គ្មានត្រូវការ API Key)"""
    raw_results = ytmusic.search(query, filter="songs", limit=limit)

    results = []
    for item in raw_results[:limit]:
        video_id = item.get("videoId")
        if not video_id:
            continue
        title = item.get("title") or "គ្មានចំណងជើង"
        artists = item.get("artists") or []
        uploader = ", ".join(a.get("name", "") for a in artists if a.get("name"))
        duration_sec = item.get("duration_seconds") or _duration_to_seconds(item.get("duration"))
        results.append({
            "id": video_id,
            "title": title,
            "duration": duration_sec,
            "uploader": uploader,
        })
    return results


def download_audio(video_id: str) -> Path:
    """ទាញយក audio (mp3) ពី YouTube video id"""
    out_template = str(DOWNLOAD_DIR / f"{video_id}.%(ext)s")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        # "android" client ជៀសផុតការចាប់ (bot detection) បានប្រសើរជាង "web"
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists():
        ydl_opts["cookiefile"] = YTDLP_COOKIES_FILE

    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    mp3_path = DOWNLOAD_DIR / f"{video_id}.mp3"
    if not mp3_path.exists():
        raise FileNotFoundError("ការទាញយកបរាជ័យ")
    return mp3_path


def cleanup_file(path: Path, delay: int = 30):
    """លុប file បន្ទាប់ពីផ្ញើរួច ដើម្បីសន្សំទំហំ Render disk"""
    def _rm():
        time.sleep(delay)
        try:
            if path.exists():
                path.unlink()
        except Exception as ex:
            log.warning("cleanup failed: %s", ex)
    threading.Thread(target=_rm, daemon=True).start()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "🎵 <b>Kairozen Song Search Bot</b>\n\n"
        "សូមវាយ <b>ចំណងជើងចម្រៀង</b> ដែលអ្នកចង់ស្វែងរក ខ្ញុំនឹងផ្ញើលទ្ធផលឲ្យអ្នកជ្រើសរើស។\n\n"
        "ឧទាហរណ៍៖ <code>ភ្លៀងធ្លាក់តែឯង</code>",
    )


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    stats = load_stats()
    uid = str(message.from_user.id)
    my_stat = stats["users"].get(uid, {"searches": 0, "downloads": 0})
    bot.reply_to(
        message,
        f"📊 <b>ស្ថិតិរបស់អ្នក</b>\n"
        f"ស្វែងរក៖ {my_stat['searches']} ដង\n"
        f"ទាញយក៖ {my_stat['downloads']} ដង\n\n"
        f"📈 <b>ស្ថិតិសរុប Bot</b>\n"
        f"ស្វែងរកសរុប៖ {stats.get('total_searches', 0)}\n"
        f"ទាញយកសរុប៖ {stats.get('total_downloads', 0)}",
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and not m.text.startswith("/"))
def handle_search(message):
    query = message.text.strip()
    if len(query) < 2:
        bot.reply_to(message, "⚠️ សូមវាយចំណងជើងឲ្យបានច្បាស់លាស់ជាងនេះ")
        return

    wait_msg = bot.reply_to(message, f"🔍 កំពុងស្វែងរក <b>{query}</b> ...")

    try:
        results = search_youtube(query)
    except Exception as ex:
        log.exception("search failed")
        bot.edit_message_text("❌ ស្វែងរកមិនបានទេ សូមព្យាយាមម្តងទៀត", message.chat.id, wait_msg.message_id)
        return

    if not results:
        bot.edit_message_text("😕 រកមិនឃើញលទ្ធផលទេ", message.chat.id, wait_msg.message_id)
        return

    record_event(message.from_user.id, "search")

    search_id = str(message.message_id)
    with CACHE_LOCK:
        SEARCH_CACHE[search_id] = results

    markup = types.InlineKeyboardMarkup(row_width=1)
    for idx, r in enumerate(results):
        label = f"{idx + 1}. {r['title'][:45]} ({format_duration(r['duration'])})"
        markup.add(types.InlineKeyboardButton(label, callback_data=f"song:{search_id}:{idx}"))

    bot.edit_message_text(
        f"🔎 លទ្ធផលសម្រាប់ <b>{query}</b>\nសូមចុចជ្រើសរើសបទ៖",
        message.chat.id, wait_msg.message_id, reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("song:"))
def handle_pick(call):
    try:
        _, search_id, idx_str = call.data.split(":", 2)
        idx = int(idx_str)
    except Exception:
        bot.answer_callback_query(call.id, "❌ ទិន្នន័យមិនត្រឹមត្រូវ")
        return

    with CACHE_LOCK:
        results = SEARCH_CACHE.get(search_id)

    if not results or idx >= len(results):
        bot.answer_callback_query(call.id, "⌛ លទ្ធផលនេះផុតកំណត់ សូមស្វែងរកម្តងទៀត")
        return

    song = results[idx]
    bot.answer_callback_query(call.id, "⬇️ កំពុងទាញយក...")
    status = bot.send_message(call.message.chat.id, f"⬇️ កំពុងទាញយក <b>{song['title']}</b> ...")

    if song["duration"] and song["duration"] > MAX_DURATION_SEC:
        bot.edit_message_text("⚠️ បទនេះវែងពេក (លើសពី ២០នាទី) សូមជ្រើសរើសបទផ្សេង",
                               call.message.chat.id, status.message_id)
        return

    try:
        mp3_path = download_audio(song["id"])
        with open(mp3_path, "rb") as f:
            bot.send_audio(
                call.message.chat.id, f,
                title=song["title"],
                performer=song["uploader"],
                caption=f"🎵 {song['title']}",
            )
        cleanup_file(mp3_path)
        bot.delete_message(call.message.chat.id, status.message_id)
        record_event(call.from_user.id, "download")
    except Exception as ex:
        log.exception("download failed")
        bot.edit_message_text("❌ ទាញយកមិនបានទេ សូមព្យាយាមបទផ្សេង", call.message.chat.id, status.message_id)


# ---------------------------------------------------------------------------
# Flask keep-alive (សម្រាប់ Render Free Web Service)
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def home():
    return "✅ Kairozen Song Search Bot កំពុងដំណើរការ"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def run_bot():
    log.info("Bot polling started...")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
