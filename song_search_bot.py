"""
Kai Music Bot
=========================
ស្វែងរក និងទាញយកចម្រៀងតាមចំណងជើង + បម្លែងអត្ថបទទៅជាសំឡេង (TTS) តាមរយៈ Telegram

របៀបប្រើ:
  /start          -> ចាប់ផ្តើម
  វាយចំណងជើងចម្រៀង -> Bot នឹងស្វែងរក 5 លទ្ធផលពី YouTube Music
                        ចុចជ្រើសរើសបទដែលចង់បាន -> Bot ផ្ញើជា audio file
  /tts <អត្ថបទ>   -> បម្លែងអត្ថបទទៅជាសំឡេង (ជ្រើសរើសសំឡេងប្រុស/ស្រី)
  /admin          -> (Admin ប៉ុណ្ណោះ) មើល User Data + Broadcast សារ

Environment Variables (កំណត់នៅលើ Render):
  BOT_TOKEN         -> Token ពី @BotFather
  ADMIN_IDS         -> Telegram user ID អ្នកគ្រប់គ្រង (comma-separated សម្រាប់ច្រើននាក់)
                       ដើម្បីមើល User Data + Broadcast សារ (default: 8266854899)
  YTDLP_COOKIES_FILE -> (ស្រេចចិត្ត) path ទៅ cookies.txt សម្រាប់ជួយការទាញយក
  DATA_DIR          -> path ទៅ Persistent Disk (Render) សម្រាប់ទុកទិន្នន័យមិនឲ្យបាត់ពេល redeploy
                       ដូចជា /data (មើល render.yaml)
  PORT              -> (Render ផ្តល់ជូនស្វ័យប្រវត្តិ)

ស្ថាបត្យកម្ម ការពារការចាប់ (anti-block):
  - SEARCH ប្រើ ytmusicapi (មិនត្រូវការ API Key, unauthenticated public search)
  - DOWNLOAD ប្រើ yt-dlp ជាមួយ android player client + cookies (ស្រេចចិត្ត) ដើម្បីកាត់បន្ថយហានិភ័យ
  - TTS ប្រើ edge-tts (Microsoft Edge voices, ឥតគិតថ្លៃ, គ្មានត្រូវការ API Key)

Dependencies (requirements.txt):
  pyTelegramBotAPI
  yt-dlp
  flask
  ytmusicapi
  edge-tts
"""

import os
import logging
import tempfile
import threading
import time
import asyncio
import uuid
from pathlib import Path

import telebot
from telebot import types
from flask import Flask
from ytmusicapi import YTMusic
import yt_dlp
import edge_tts

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("❌ សូមកំណត់ Environment Variable ឈ្មោះ BOT_TOKEN ជាមុនសិន")

# Cookies file សម្រាប់ yt-dlp download (ជៀសវាងការចាប់ពេលទាញយក) - ស្រេចចិត្ត
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "")  # e.g. /etc/secrets/cookies.txt

# Admin IDs (Telegram user id) អាចមើល User Data + Broadcast សារ
# ដាក់ច្រើននាក់បាន បំបែកដោយ comma ឧ. "8266854899,123456789"
ADMIN_IDS = set()
for _part in os.environ.get("ADMIN_IDS", "8266854899").split(","):
    _part = _part.strip()
    if _part.isdigit():
        ADMIN_IDS.add(int(_part))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


MAX_RESULTS = 5          # ចំនួនលទ្ធផលស្វែងរកបង្ហាញ
MAX_DURATION_SEC = 1200  # កំណត់រយៈពេលអតិបរមា ២០នាទី (ការពារ file ធំពេក)
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "kairozen_song_bot"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# TTS (Text-to-Speech) config - ប្រើ edge-tts (ឥតគិតថ្លៃ, គ្មានត្រូវការ API Key)
# ---------------------------------------------------------------------------
MAX_TTS_CHARS = 500  # កំណត់ប្រវែងអត្ថបទអតិបរមា
TTS_VOICES = {
    "female": "km-KH-SreymomNeural",
    "male": "km-KH-PisethNeural",
}

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


_KIND_LABELS = {"search": "ស្វែងរក", "download": "ទាញយក", "tts": "បម្លែងសំឡេង (TTS)"}


def record_event(user_id: int, kind: str):
    """kind: 'search' / 'download' / 'tts' - រក្សាទុកជា JSON លើ persistent disk"""
    with STATS_LOCK:
        stats = load_stats()
        stats[f"total_{kind}"] = stats.get(f"total_{kind}", 0) + 1
        uid = str(user_id)
        user_stat = stats["users"].setdefault(uid, {})
        user_stat[kind] = user_stat.get(kind, 0) + 1
        save_stats(stats)


# ---------------------------------------------------------------------------
# User directory (សម្រាប់ Admin Panel: មើល User Data + Broadcast)
# ---------------------------------------------------------------------------
USERS_FILE = DATA_DIR / "users.json"
USERS_LOCK = threading.Lock()


def load_users() -> dict:
    if USERS_FILE.exists():
        try:
            import json
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("users.json corrupted, starting fresh")
    return {}


def save_users(users: dict):
    import json
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERS_FILE)


def register_user(user):
    """កត់ត្រាអ្នកប្រើរាល់ពេលមាន message ចូល - ប្រើសម្រាប់ Admin Panel"""
    if not user:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with USERS_LOCK:
        users = load_users()
        uid = str(user.id)
        if uid not in users:
            users[uid] = {
                "username": user.username or "",
                "first_name": user.first_name or "",
                "joined_at": now,
                "last_active": now,
            }
        else:
            users[uid]["last_active"] = now
            if user.username:
                users[uid]["username"] = user.username
            if user.first_name:
                users[uid]["first_name"] = user.first_name
        save_users(users)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("song_search_bot")

# ត្រូវ enable មុនបង្កើត bot instance ដើម្បីប្រើ @bot.middleware_handler
telebot.apihelper.ENABLE_MIDDLEWARE = True

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


@bot.middleware_handler(update_types=["message"])
def track_user_middleware(bot_instance, message):
    """កត់ត្រា user គ្រប់ message ចូល - ប្រើសម្រាប់ Admin Panel (User Data)"""
    try:
        register_user(message.from_user)
    except Exception as ex:
        log.warning("user tracking failed: %s", ex)

# YTMusic() ដោយគ្មាន auth file -> public unauthenticated search (គ្មានត្រូវការ Key)
ytmusic = YTMusic()

# in-memory cache: {search_id: [ {id, title, duration, uploader}, ... ]}
SEARCH_CACHE: dict[str, list[dict]] = {}
CACHE_LOCK = threading.Lock()

# in-memory cache: {tts_id: text} - រក្សាទុកអត្ថបទបណ្តោះអាសន្នរង់ចាំជ្រើសរើសសំឡេង
TTS_CACHE: dict[str, str] = {}

# in-memory cache: {broadcast_id: (source_chat_id, source_message_id)}
BROADCAST_CACHE: dict[str, tuple] = {}


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
    """ទាញយក audio (mp3) ពី YouTube video id
    សាកល្បង player client ជាច្រើនតាមលំដាប់ (fallback chain) ដើម្បីជៀសវាង
    'Sign in to confirm you're not a bot' ដែលកើតលើ client ខ្លះ។
    """
    out_template = str(DOWNLOAD_DIR / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"

    # លំដាប់ client ត្រូវសាកល្បង - ios/android_music ជាធម្មតាមិនសូវត្រូវ block
    # ដូច web/android ព្រោះមិនតម្រូវ PO Token ដូចគ្នា
    CLIENT_CHAIN = ["ios", "android_music", "android", "tv_embedded", "web"]

    mp3_path = DOWNLOAD_DIR / f"{video_id}.mp3"
    last_error = None

    for client in CLIENT_CHAIN:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "noplaylist": True,
            "extractor_args": {"youtube": {"player_client": [client]}},
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists():
            ydl_opts["cookiefile"] = YTDLP_COOKIES_FILE

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if mp3_path.exists():
                log.info("download succeeded with client=%s", client)
                return mp3_path
        except Exception as ex:
            last_error = ex
            log.warning("client=%s failed: %s", client, ex)
            continue

    raise FileNotFoundError(f"ការទាញយកបរាជ័យលើ client ទាំងអស់: {last_error}")


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


def generate_tts(text: str, voice: str) -> Path:
    """បម្លែងអត្ថបទទៅជាសំឡេង (mp3) ដោយប្រើ edge-tts"""
    out_path = DOWNLOAD_DIR / f"tts_{uuid.uuid4().hex}.mp3"

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out_path))

    asyncio.run(_run())

    if not out_path.exists():
        raise FileNotFoundError("ការបម្លែងសំឡេងបរាជ័យ")
    return out_path


# ---------------------------------------------------------------------------
# Main menu buttons (Reply Keyboard - នៅជាប់ជានិច្ចនៅផ្នែកខាងក្រោម chat)
# ---------------------------------------------------------------------------
BTN_SEARCH = "🔍 ស្វែងរកចម្រៀង"
BTN_TTS = "🔊 បម្លែងអត្ថបទជាសំឡេង"
BTN_STATS = "📊 ស្ថិតិរបស់ខ្ញុំ"

MAIN_MENU = types.ReplyKeyboardMarkup(resize_keyboard=True)
MAIN_MENU.row(BTN_SEARCH, BTN_TTS)
MAIN_MENU.row(BTN_STATS)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
BOT_NAME = "🎵 Kai Music"


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    first_name = message.from_user.first_name or "មិត្តភក្តិ"
    bot.send_message(
        message.chat.id,
        f"👋 សួស្តី <b>{first_name}</b>!\n\n"
        f"សូមស្វាគមន៍មកកាន់ <b>{BOT_NAME}</b> 🎧\n"
        "ជំនួយការស្វែងរកចម្រៀង និងបម្លែងអត្ថបទជាសំឡេងរបស់អ្នក។\n\n"
        "✨ <b>អ្វីដែលខ្ញុំធ្វើបាន៖</b>\n"
        "🔍 ស្វែងរក ​និងទាញយកចម្រៀងតាមចំណងជើង\n"
        "🔊 បម្លែងអត្ថបទទៅជាសំឡេង (ខ្មែរ/អង់គ្លេស)\n\n"
        "👇 ជ្រើសរើសមុខងារពីប៊ូតុងខាងក្រោម ឬវាយចំណងជើងចម្រៀងផ្ទាល់៖",
        reply_markup=MAIN_MENU,
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_SEARCH)
def btn_search(message):
    msg = bot.reply_to(message, "🔍 សូមវាយ <b>ចំណងជើងចម្រៀង</b> ដែលអ្នកចង់ស្វែងរក")
    bot.register_next_step_handler(msg, handle_search)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_TTS)
def btn_tts(message):
    msg = bot.reply_to(message, "🔊 សូមផ្ញើអត្ថបទដែលអ្នកចង់បម្លែងទៅជាសំឡេង (ខ្មែរ ឬអង់គ្លេស)")
    bot.register_next_step_handler(msg, _process_tts_text)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_STATS)
def btn_stats(message):
    cmd_stats(message)


# ---------------------------------------------------------------------------
# Admin Panel (មើល User Data + Broadcast សារទៅអ្នកប្រើទាំងអស់)
# ---------------------------------------------------------------------------
@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if not is_admin(message.from_user.id):
        return  # មិនឆ្លើយតបទាល់តែសោះ ដើម្បីមិនបង្ហាញថាមាន admin feature

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👥 អ្នកប្រើប្រាស់", callback_data="admin:users"),
        types.InlineKeyboardButton("📊 ស្ថិតិទាំងអស់", callback_data="admin:stats"),
        types.InlineKeyboardButton("📢 ផ្ញើសារទៅអ្នកប្រើទាំងអស់", callback_data="admin:broadcast"),
    )
    bot.send_message(message.chat.id, "🛠 <b>Kai Music — Admin Panel</b>", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:"))
def handle_admin_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ អ្នកគ្មានសិទ្ធិប្រើមុខងារនេះទេ")
        return

    action = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)

    if action == "users":
        users = load_users()
        total = len(users)
        items = sorted(users.items(), key=lambda kv: kv[1].get("joined_at", ""), reverse=True)[:15]
        lines = [f"👥 <b>អ្នកប្រើសរុប៖ {total}</b>", ""]
        for uid, info in items:
            uname = f"@{info['username']}" if info.get("username") else (info.get("first_name") or "(គ្មានឈ្មោះ)")
            lines.append(f"• {uname} — <code>{uid}</code>\n  ចូលចាប់ផ្តើម៖ {info.get('joined_at', '?')}")
        if not items:
            lines.append("មិនទាន់មានអ្នកប្រើទេ")
        bot.send_message(call.message.chat.id, "\n".join(lines))

    elif action == "stats":
        stats = load_stats()
        users = load_users()
        lines = [f"📊 <b>ស្ថិតិសរុប Bot</b>", f"អ្នកប្រើសរុប៖ {len(users)}", ""]
        for kind, label in _KIND_LABELS.items():
            lines.append(f"{label}សរុប៖ {stats.get(f'total_{kind}', 0)}")
        bot.send_message(call.message.chat.id, "\n".join(lines))

    elif action == "broadcast":
        msg = bot.send_message(
            call.message.chat.id,
            "📢 សូមផ្ញើសារដែលអ្នកចង់ Broadcast (អត្ថបទ/រូបភាព/វីដេអូ/file អ្វីក៏បាន)",
        )
        bot.register_next_step_handler(msg, _capture_broadcast_content)


def _capture_broadcast_content(message):
    if not is_admin(message.from_user.id):
        return

    bid = uuid.uuid4().hex[:10]
    with CACHE_LOCK:
        BROADCAST_CACHE[bid] = (message.chat.id, message.message_id)

    users = load_users()
    count = len(users)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ បញ្ជាក់ផ្ញើ", callback_data=f"bcast:{bid}:go"),
        types.InlineKeyboardButton("❌ បោះបង់", callback_data=f"bcast:{bid}:cancel"),
    )
    bot.reply_to(message, f"📢 នឹងផ្ញើសារនេះទៅអ្នកប្រើ <b>{count}</b> នាក់។ បញ្ជាក់ទេ?", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bcast:"))
def handle_broadcast_confirm(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ អ្នកគ្មានសិទ្ធិប្រើមុខងារនេះទេ")
        return

    try:
        _, bid, action = call.data.split(":", 2)
    except Exception:
        bot.answer_callback_query(call.id, "❌ ទិន្នន័យមិនត្រឹមត្រូវ")
        return

    with CACHE_LOCK:
        ref = BROADCAST_CACHE.pop(bid, None)

    if action == "cancel" or not ref:
        bot.answer_callback_query(call.id, "បានបោះបង់")
        bot.edit_message_text("❌ បានបោះបង់ Broadcast", call.message.chat.id, call.message.message_id)
        return

    bot.answer_callback_query(call.id, "🚀 កំពុងផ្ញើ...")
    bot.edit_message_text("🚀 កំពុងផ្ញើសារទៅអ្នកប្រើទាំងអស់... (នេះអាចចំណាយពេលបន្តិច)",
                           call.message.chat.id, call.message.message_id)

    src_chat_id, src_msg_id = ref
    threading.Thread(
        target=_run_broadcast,
        args=(call.message.chat.id, call.message.message_id, src_chat_id, src_msg_id),
        daemon=True,
    ).start()


def _run_broadcast(admin_chat_id: int, status_msg_id: int, src_chat_id: int, src_msg_id: int):
    """ផ្ញើសារទៅអ្នកប្រើទាំងអស់ដោយប្រើ copy_message (support content ណាមួយក៏បាន)"""
    users = load_users()
    total = len(users)
    success = 0
    failed = 0

    for uid_str in list(users.keys()):
        try:
            bot.copy_message(int(uid_str), src_chat_id, src_msg_id)
            success += 1
        except Exception as ex:
            failed += 1
            log.debug("broadcast failed for %s: %s", uid_str, ex)
        time.sleep(0.05)  # ជៀសវាង Telegram rate limit (~20 msg/sec)

    summary = (
        f"✅ <b>Broadcast រួចរាល់!</b>\n"
        f"សរុប៖ {total}\n"
        f"ជោគជ័យ៖ {success}\n"
        f"បរាជ័យ៖ {failed} (ប្រហែលជា block bot ឬលុប chat)"
    )
    try:
        bot.edit_message_text(summary, admin_chat_id, status_msg_id)
    except Exception:
        bot.send_message(admin_chat_id, summary)


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    stats = load_stats()
    uid = str(message.from_user.id)
    my_stat = stats["users"].get(uid, {})
    lines = ["📊 <b>ស្ថិតិរបស់អ្នក</b>"]
    for kind, label in _KIND_LABELS.items():
        lines.append(f"{label}៖ {my_stat.get(kind, 0)} ដង")
    lines.append("")
    lines.append("📈 <b>ស្ថិតិសរុប Bot</b>")
    for kind, label in _KIND_LABELS.items():
        lines.append(f"{label}សរុប៖ {stats.get(f'total_{kind}', 0)}")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["tts"])
def cmd_tts(message):
    text = message.text.partition(" ")[2].strip()
    if not text:
        msg = bot.reply_to(message, "🔊 សូមផ្ញើអត្ថបទដែលអ្នកចង់បម្លែងទៅជាសំឡេង (ខ្មែរ ឬអង់គ្លេស)")
        bot.register_next_step_handler(msg, _process_tts_text)
        return
    _start_tts_flow(message, text)


def _process_tts_text(message):
    if message.content_type != "text":
        bot.reply_to(message, "⚠️ សូមផ្ញើជាអត្ថបទ")
        return
    _start_tts_flow(message, message.text.strip())


def _start_tts_flow(message, text: str):
    if not text:
        bot.reply_to(message, "⚠️ អត្ថបទទទេ សូមព្យាយាមម្តងទៀត")
        return
    if len(text) > MAX_TTS_CHARS:
        bot.reply_to(message, f"⚠️ អត្ថបទវែងពេក (កំណត់អតិបរមា {MAX_TTS_CHARS} តួអក្សរ)")
        return

    tts_id = uuid.uuid4().hex[:10]
    with CACHE_LOCK:
        TTS_CACHE[tts_id] = text

    preview = text if len(text) <= 200 else text[:200] + "..."
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👩 សំឡេងស្រី", callback_data=f"tts:{tts_id}:female"),
        types.InlineKeyboardButton("👨 សំឡេងប្រុស", callback_data=f"tts:{tts_id}:male"),
    )
    bot.reply_to(message, f"🔊 សូមជ្រើសរើសសំឡេងសម្រាប់៖\n<i>{preview}</i>", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("tts:"))
def handle_tts_pick(call):
    try:
        _, tts_id, voice_key = call.data.split(":", 2)
    except Exception:
        bot.answer_callback_query(call.id, "❌ ទិន្នន័យមិនត្រឹមត្រូវ")
        return

    with CACHE_LOCK:
        text = TTS_CACHE.pop(tts_id, None)

    if not text:
        bot.answer_callback_query(call.id, "⌛ សំណើនេះផុតកំណត់ សូមព្យាយាមម្តងទៀត")
        return

    voice = TTS_VOICES.get(voice_key, TTS_VOICES["female"])
    bot.answer_callback_query(call.id, "🔊 កំពុងបង្កើតសំឡេង...")
    status = bot.send_message(call.message.chat.id, "🔊 កំពុងបង្កើតសំឡេង...")

    try:
        audio_path = generate_tts(text, voice)
        with open(audio_path, "rb") as f:
            bot.send_voice(call.message.chat.id, f)
        cleanup_file(audio_path, delay=15)
        bot.delete_message(call.message.chat.id, status.message_id)
        record_event(call.from_user.id, "tts")
    except Exception as ex:
        log.exception("tts failed")
        bot.edit_message_text("❌ បម្លែងសំឡេងមិនបានទេ សូមព្យាយាមម្តងទៀត",
                               call.message.chat.id, status.message_id)


@bot.message_handler(func=lambda m: m.content_type == "text" and not m.text.startswith("/")
                      and m.text not in (BTN_SEARCH, BTN_TTS, BTN_STATS))
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
    return "✅ Kai Music Bot កំពុងដំណើរការ"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def run_bot():
    log.info("Bot polling started...")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
