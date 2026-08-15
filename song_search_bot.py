"""
Kai Music Bot
=========================
ស្វែងរក និងទាញយកចម្រៀងតាមចំណងជើង + បម្លែងអត្ថបទទៅជាសំឡេង (TTS) តាមរយៈ Telegram

របៀបប្រើ:
  /start          -> ចាប់ផ្តើម
  វាយចំណងជើងចម្រៀង -> Bot នឹងស្វែងរក 5 លទ្ធផលពី YouTube Music
                        ចុចជ្រើសរើសបទដែលចង់បាន -> Bot ផ្ញើជា audio file
  /tts <អត្ថបទ>   -> បម្លែងអត្ថបទទៅជាសំឡេង (ជ្រើសរើសសំឡេងប្រុស/ស្រី)
  ផ្ញើរូបភាព       -> ធ្វើឲ្យរូបភាពច្បាស់ស្វ័យប្រវត្តិ (upscale + sharpen)
                     ឬចុច "✂️ កាត់ផ្ទៃខាងក្រោយ" ដើម្បីកាត់ background ចេញ
                     ឬចុច "🔗 ធ្វើរូបភាពជា URL" ដើម្បីទទួល link ថេរ
                     ឬចុច "📝 Copy អក្សរពីរូបភាព" ដើម្បីទាញអក្សរចេញ (OCR)
  /admin          -> (Admin ប៉ុណ្ណោះ) មើល User Data + Broadcast សារ
  /referral       -> មើល link ណែនាំមិត្ត + ស្ថិតិ bonus

Rate Limiting (Fair Use):
  - មុខងារនីមួយៗ (search/tts/enhance/removebg/img2url) ប្រើបានតែ 2 ដង/12ម៉ោង/user
  - ណែនាំមិត្ត 1 នាក់ចូលរួម Bot (តាម /referral link) = ទទួល +2 ដងបន្ថែម
  - Admin (តាម ADMIN_IDS) មិនកំណត់ទេ

Environment Variables (កំណត់នៅលើ Render):
  BOT_TOKEN         -> Token ពី @BotFather
  ADMIN_IDS         -> Telegram user ID អ្នកគ្រប់គ្រង (comma-separated សម្រាប់ច្រើននាក់)
                       ដើម្បីមើល User Data + Broadcast សារ (default: 8266854899)
  FORCE_SUB_CHANNEL      -> @username របស់ Channel ដែលតម្រូវ join (ទុកទទេ = បិទមុខងារនេះ)
  FORCE_SUB_CHANNEL_LINK -> link ចូលរួម Channel (ឧ. https://t.me/channelusername)
                       ⚠️ Bot ត្រូវតែជា Admin ក្នុង Channel នេះ
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
  Pillow
  rembg
  requests
  pytesseract
"""

import os
import logging
import tempfile
import threading
import time
import asyncio
import uuid
import html
from pathlib import Path

import telebot
from telebot import types
from flask import Flask
from ytmusicapi import YTMusic
import yt_dlp
import edge_tts
import requests

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


# ---------------------------------------------------------------------------
# Force-Subscribe Channel (តម្រូវ join channel មុនប្រើ Bot)
# FORCE_SUB_CHANNEL     -> @username របស់ channel (ត្រូវការសម្រាប់ check membership)
# FORCE_SUB_CHANNEL_LINK -> link សម្រាប់ជាប៊ូតុង join (ឧ. https://t.me/channelusername)
# ទុកទទេទាំងពីរ ដើម្បីបិទមុខងារនេះ (មិនតម្រូវ)
# ⚠️ Bot ត្រូវតែជា Admin ក្នុង Channel នេះ ទើប check membership បាន
# ---------------------------------------------------------------------------
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "").strip()
FORCE_SUB_CHANNEL_LINK = os.environ.get("FORCE_SUB_CHANNEL_LINK", "").strip()


def is_subscribed(user_id: int) -> bool:
    """ត្រួតពិនិត្យថា user បាន join Force-Sub Channel ដែរឬទេ។
    Admin និង feature ដែលបិទ (គ្មាន FORCE_SUB_CHANNEL) នឹងឆ្លងកាត់ដោយស្វ័យប្រវត្តិ។
    """
    if is_admin(user_id):
        return True
    if not FORCE_SUB_CHANNEL:
        return True
    try:
        member = bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as ex:
        log.warning("force-sub check failed (fail-open): %s", ex)
        return True  # បើ check បរាជ័យ (ឧ. bot មិនមែន admin) កុំទប់ user ទាំងអស់


def send_force_sub_prompt(chat_id: int):
    if not FORCE_SUB_CHANNEL_LINK:
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 ចូលរួម Channel", url=FORCE_SUB_CHANNEL_LINK),
        types.InlineKeyboardButton("✅ ខ្ញុំបានចូលរួមហើយ", callback_data="checksub"),
    )
    bot.send_message(
        chat_id,
        "🔒 <b>ត្រូវការចូលរួម Channel មុនប្រើ Bot</b>\n\n"
        "សូមចុចប៊ូតុងខាងក្រោមដើម្បីចូលរួម Channel របស់យើង "
        "រួចចុច «ខ្ញុំបានចូលរួមហើយ»៖",
        reply_markup=markup,
    )


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


_KIND_LABELS = {
    "search": "ស្វែងរក",
    "download": "ទាញយក",
    "tts": "បម្លែងសំឡេង (TTS)",
    "enhance": "ធ្វើរូបភាពច្បាស់",
    "removebg": "កាត់ផ្ទៃខាងក្រោយ",
    "img2url": "រូបភាពទៅ URL",
    "ocr": "Copy អក្សរពីរូបភាព",
}


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


def register_user(user) -> bool:
    """កត់ត្រាអ្នកប្រើរាល់ពេលមាន message ចូល - ត្រឡប់ True បើជា user ថ្មី"""
    if not user:
        return False
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    is_new = False
    with USERS_LOCK:
        users = load_users()
        uid = str(user.id)
        if uid not in users:
            is_new = True
            users[uid] = {
                "username": user.username or "",
                "first_name": user.first_name or "",
                "joined_at": now,
                "last_active": now,
                "bonus_credits": 0,
                "referral_count": 0,
                "referred_by": None,
            }
        else:
            users[uid]["last_active"] = now
            if user.username:
                users[uid]["username"] = user.username
            if user.first_name:
                users[uid]["first_name"] = user.first_name
        save_users(users)
    return is_new


# ---------------------------------------------------------------------------
# Rate Limiting + Referral (2 ครั้ง/12ម៉ោង/មុខងារ, ណែនាំមិត្ត 1 នាក់ = +2 ដងបន្ថែម)
# ---------------------------------------------------------------------------
USAGE_FILE = DATA_DIR / "usage.json"
USAGE_LOCK = threading.Lock()

FREE_LIMIT_PER_WINDOW = 2
WINDOW_HOURS = 12
BONUS_PER_REFERRAL = 2

_BOT_USERNAME_CACHE = None


def load_usage() -> dict:
    if USAGE_FILE.exists():
        try:
            import json
            return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("usage.json corrupted, starting fresh")
    return {}


def save_usage(usage: dict):
    import json
    tmp = USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USAGE_FILE)


def check_and_consume_quota(user_id: int, kind: str) -> bool:
    """ត្រូវ 2 ครั้ง/12ម៉ោង/មុខងារ (kind) - Admin មិនកំណត់ទេ
    បើអស់ quota ឥតគិតថ្លៃ ព្យាយាមប្រើ bonus_credits (ទទួលបានពី referral) ជំនួស
    """
    if is_admin(user_id):
        return True

    now = time.time()
    window_start = now - WINDOW_HOURS * 3600
    uid = str(user_id)

    with USAGE_LOCK:
        usage = load_usage()
        timestamps = [t for t in usage.get(uid, {}).get(kind, []) if t > window_start]

        if len(timestamps) < FREE_LIMIT_PER_WINDOW:
            timestamps.append(now)
            usage.setdefault(uid, {})[kind] = timestamps
            save_usage(usage)
            return True

        # អស់ quota ឥតគិតថ្លៃហើយ - សាកល្បង bonus credit
        with USERS_LOCK:
            users = load_users()
            if users.get(uid, {}).get("bonus_credits", 0) > 0:
                users[uid]["bonus_credits"] -= 1
                save_users(users)
                timestamps.append(now)
                usage.setdefault(uid, {})[kind] = timestamps
                save_usage(usage)
                return True

    return False


def get_bot_username() -> str:
    global _BOT_USERNAME_CACHE
    if _BOT_USERNAME_CACHE is None:
        try:
            _BOT_USERNAME_CACHE = bot.get_me().username
        except Exception as ex:
            log.warning("get bot username failed: %s", ex)
            _BOT_USERNAME_CACHE = ""
    return _BOT_USERNAME_CACHE


def build_referral_link(user_id: int) -> str:
    username = get_bot_username()
    if not username:
        return ""
    return f"https://t.me/{username}?start=ref{user_id}"


def credit_referral(referrer_id: int, new_user_id: int) -> bool:
    """ផ្តល់ bonus +2 ដងទៅ referrer ពេលមានមិត្តថ្មីចូលរួមតាម link របស់គេ
    ត្រឡប់ True បើផ្តល់ credit ជោគជ័យ (គ្មាន double-credit)
    """
    if referrer_id == new_user_id:
        return False
    with USERS_LOCK:
        users = load_users()
        ref_uid, new_uid = str(referrer_id), str(new_user_id)
        if ref_uid not in users or new_uid not in users:
            return False
        if users[new_uid].get("referred_by"):
            return False  # already credited ដងមុនហើយ
        users[new_uid]["referred_by"] = ref_uid
        users[ref_uid]["bonus_credits"] = users[ref_uid].get("bonus_credits", 0) + BONUS_PER_REFERRAL
        users[ref_uid]["referral_count"] = users[ref_uid].get("referral_count", 0) + 1
        save_users(users)
        return True


def send_quota_exceeded(chat_id: int, user_id: int, kind: str):
    label = _KIND_LABELS.get(kind, kind)
    link = build_referral_link(user_id)
    text = (
        f"⏳ អ្នកបានប្រើមុខងារ <b>{label}</b> គ្រប់ចំនួន {FREE_LIMIT_PER_WINDOW} ដង "
        f"ក្នុងរយៈពេល {WINDOW_HOURS} ម៉ោងហើយ។\n\n"
        f"ចង់ប្រើបន្ត? ណែនាំមិត្ត ១ នាក់ចូលរួម Bot នេះ តាម link ខាងក្រោម "
        f"នឹងទទួលបានសិទ្ធិប្រើបន្ថែម {BONUS_PER_REFERRAL} ដងភ្លាមៗ៖"
    )
    if link:
        text += f"\n\n<code>{link}</code>"
    bot.send_message(chat_id, text)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("song_search_bot")

# ត្រូវ enable មុនបង្កើត bot instance ដើម្បីប្រើ @bot.middleware_handler
telebot.apihelper.ENABLE_MIDDLEWARE = True

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


@bot.middleware_handler(update_types=["message"])
def track_user_middleware(bot_instance, message):
    """កត់ត្រា user គ្រប់ message ចូល - ដាក់ flag is_new_user លើ message សម្រាប់ referral"""
    try:
        message.is_new_user = register_user(message.from_user)
    except Exception as ex:
        log.warning("user tracking failed: %s", ex)
        message.is_new_user = False

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
# Image Enhancement (ធ្វើឲ្យរូបភាពច្បាស់: upscale + sharpen + contrast)
# ---------------------------------------------------------------------------
MAX_ENHANCE_DIM = 2200   # ដែនកំណត់ pixel អតិបរមា (ការពារ memory លើសលប់លើ free/starter plan)
ENHANCE_UPSCALE = 2      # ដង upscale


def enhance_image(input_path: Path) -> Path:
    """ធ្វើឲ្យរូបភាពច្បាស់ជាងមុន៖ upscale (LANCZOS) + unsharp mask + contrast/color boost"""
    from PIL import Image, ImageFilter, ImageEnhance

    img = Image.open(input_path).convert("RGB")
    w, h = img.size

    new_w, new_h = w * ENHANCE_UPSCALE, h * ENHANCE_UPSCALE
    if max(new_w, new_h) > MAX_ENHANCE_DIM:
        ratio = MAX_ENHANCE_DIM / max(w, h)
        new_w, new_h = max(1, int(w * ratio)), max(1, int(h * ratio))

    img = img.resize((new_w, new_h), Image.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.3)

    out_path = DOWNLOAD_DIR / f"enhanced_{uuid.uuid4().hex}.jpg"
    img.save(out_path, "JPEG", quality=95)
    return out_path


# ---------------------------------------------------------------------------
# Background Removal (កាត់ផ្ទៃខាងក្រោយចេញ - ប្រើ rembg, model ស្រាល u2netp)
# Model cache ទុកក្នុង DATA_DIR ដើម្បីកុំឲ្យ download ថ្មីរាល់ครั้ง redeploy
# ---------------------------------------------------------------------------
os.environ.setdefault("U2NET_HOME", str(DATA_DIR / "u2net_models"))

_REMBG_SESSION = None
_REMBG_LOCK = threading.Lock()


def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        with _REMBG_LOCK:
            if _REMBG_SESSION is None:
                from rembg import new_session
                log.info("loading rembg model (u2netp) - ដំបូងអាចយូរបន្តិចដើម្បី download...")
                _REMBG_SESSION = new_session("u2netp")
    return _REMBG_SESSION


def remove_background(input_path: Path) -> Path:
    """កាត់ផ្ទៃខាងក្រោយចេញ -> PNG មាន alpha channel (ថ្លា)"""
    from rembg import remove

    session = _get_rembg_session()
    input_bytes = input_path.read_bytes()
    output_bytes = remove(input_bytes, session=session)

    out_path = DOWNLOAD_DIR / f"nobg_{uuid.uuid4().hex}.png"
    out_path.write_bytes(output_bytes)
    return out_path


# ---------------------------------------------------------------------------
# Image -> URL (Upload រូបភាពទៅ Catbox.moe ដើម្បីទទួល link ថេរ, ឥតគិតថ្លៃ គ្មានត្រូវការ Key)
# ---------------------------------------------------------------------------
def upload_to_catbox(file_path: Path) -> str:
    """Upload file ទៅ catbox.moe (anonymous, ឥតគិតថ្លៃ, ទុកអចិន្ត្រៃយ៍) -> ត្រឡប់ URL ថេរ"""
    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=30,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise ValueError(f"Catbox upload response មិនត្រឹមត្រូវ: {url}")
    return url


# ---------------------------------------------------------------------------
# OCR (Copy អក្សរពីរូបភាព) - ប្រើ Tesseract OCR (ខ្មែរ + អង់គ្លេស)
# ---------------------------------------------------------------------------
def extract_text_from_image(input_path: Path) -> str:
    """ទាញអក្សរចេញពីរូបភាព (khm+eng) ដោយប្រើ pytesseract"""
    from PIL import Image
    import pytesseract

    img = Image.open(input_path)
    text = pytesseract.image_to_string(img, lang="khm+eng")
    return text.strip()


# ---------------------------------------------------------------------------
# Main menu buttons (Reply Keyboard - នៅជាប់ជានិច្ចនៅផ្នែកខាងក្រោម chat)
# ---------------------------------------------------------------------------
BTN_SEARCH = "🔍 ស្វែងរកចម្រៀង"
BTN_TTS = "🔊 បម្លែងអត្ថបទជាសំឡេង"
BTN_ENHANCE = "🖼 ធ្វើឲ្យរូបភាពច្បាស់"
BTN_REMOVE_BG = "✂️ កាត់ផ្ទៃខាងក្រោយ"
BTN_IMG_URL = "🔗 ធ្វើរូបភាពជា URL"
BTN_OCR = "📝 Copy អក្សរពីរូបភាព"
BTN_STATS = "📊 ស្ថិតិរបស់ខ្ញុំ"

MAIN_MENU = types.ReplyKeyboardMarkup(resize_keyboard=True)
MAIN_MENU.row(BTN_SEARCH, BTN_TTS)
MAIN_MENU.row(BTN_ENHANCE, BTN_REMOVE_BG)
MAIN_MENU.row(BTN_IMG_URL, BTN_OCR)
MAIN_MENU.row(BTN_STATS)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
BOT_NAME = "🎵 Kai Music"


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    first_name = message.from_user.first_name or "មិត្តភក្តិ"

    # ដោះស្រាយ referral payload: /start ref<user_id>
    parts = message.text.split(maxsplit=1)
    if getattr(message, "is_new_user", False) and len(parts) > 1 and parts[1].startswith("ref"):
        try:
            referrer_id = int(parts[1][3:])
            if credit_referral(referrer_id, message.from_user.id):
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎉 មិត្តរបស់អ្នក <b>{first_name}</b> បានចូលរួម {BOT_NAME} តាម link របស់អ្នក!\n"
                        f"អ្នកទទួលបានសិទ្ធិប្រើបន្ថែម {BONUS_PER_REFERRAL} ដងភ្លាមៗ 🎁",
                    )
                except Exception:
                    pass
        except (ValueError, IndexError):
            pass

    bot.send_message(
        message.chat.id,
        f"👋 សួស្តី <b>{first_name}</b>!\n\n"
        f"សូមស្វាគមន៍មកកាន់ <b>{BOT_NAME}</b> 🎧\n"
        "ជំនួយការស្វែងរកចម្រៀង និងបម្លែងអត្ថបទជាសំឡេងរបស់អ្នក។\n\n"
        "✨ <b>អ្វីដែលខ្ញុំធ្វើបាន៖</b>\n"
        "🔍 ស្វែងរក ​និងទាញយកចម្រៀងតាមចំណងជើង\n"
        "🔊 បម្លែងអត្ថបទទៅជាសំឡេង (ខ្មែរ/អង់គ្លេស)\n"
        "🖼 ធ្វើឲ្យរូបភាពច្បាស់ (upscale + sharpen)\n"
        "✂️ កាត់ផ្ទៃខាងក្រោយចេញ (background removal)\n"
        "🔗 ធ្វើរូបភាពជា URL (link ថេរអាចចែករំលែក)\n"
        "📝 Copy អក្សរពីរូបភាព (OCR ខ្មែរ/អង់គ្លេស)\n\n"
        f"⏳ <i>មុខងារនីមួយៗប្រើបាន {FREE_LIMIT_PER_WINDOW} ដងក្នុង {WINDOW_HOURS} ម៉ោង។ "
        f"ណែនាំមិត្ត ១ នាក់ = +{BONUS_PER_REFERRAL} ដងបន្ថែម (មើល /referral)</i>\n\n"
        "👇 ជ្រើសរើសមុខងារពីប៊ូតុងខាងក្រោម ឬវាយចំណងជើងចម្រៀងផ្ទាល់៖",
        reply_markup=MAIN_MENU,
    )
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)


@bot.message_handler(commands=["referral"])
def cmd_referral(message):
    users = load_users()
    my = users.get(str(message.from_user.id), {})
    link = build_referral_link(message.from_user.id)
    bot.reply_to(
        message,
        f"🎁 <b>Link ណែនាំមិត្តរបស់អ្នក៖</b>\n<code>{link}</code>\n\n"
        f"👥 មិត្តដែលចូលរួមរួច៖ {my.get('referral_count', 0)} នាក់\n"
        f"⭐ សិទ្ធិប្រើបន្ថែមនៅសល់៖ {my.get('bonus_credits', 0)} ដង\n\n"
        f"រាល់ครั้งមិត្តម្នាក់ chat ជាមួយ link នេះ អ្នកទទួលបាន +{BONUS_PER_REFERRAL} ដងភ្លាមៗ!",
    )


@bot.callback_query_handler(func=lambda c: c.data == "checksub")
def handle_checksub(call):
    if is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ អរគុណ! អ្នកអាចប្រើ Bot បានហើយ")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "🎉 ជោគជ័យ! ចុច /start ដើម្បីចាប់ផ្តើមប្រើ Bot")
    else:
        bot.answer_callback_query(call.id, "❌ អ្នកមិនទាន់ចូលរួម Channel នៅឡើយទេ", show_alert=True)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_SEARCH)
def btn_search(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "🔍 សូមវាយ <b>ចំណងជើងចម្រៀង</b> ដែលអ្នកចង់ស្វែងរក")
    bot.register_next_step_handler(msg, handle_search)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_TTS)
def btn_tts(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "🔊 សូមផ្ញើអត្ថបទដែលអ្នកចង់បម្លែងទៅជាសំឡេង (ខ្មែរ ឬអង់គ្លេស)")
    bot.register_next_step_handler(msg, _process_tts_text)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_ENHANCE)
def btn_enhance(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "🖼 សូមផ្ញើ<b>រូបភាព</b>ដែលអ្នកចង់ធ្វើឲ្យច្បាស់ (ខ្ញុំនឹង upscale + sharpen ស្វ័យប្រវត្តិ)")
    bot.register_next_step_handler(msg, _process_enhance_photo)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_REMOVE_BG)
def btn_remove_bg(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "✂️ សូមផ្ញើ<b>រូបភាព</b>ដែលអ្នកចង់កាត់ផ្ទៃខាងក្រោយចេញ")
    bot.register_next_step_handler(msg, _process_removebg_photo)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_IMG_URL)
def btn_img_url(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "🔗 សូមផ្ញើ<b>រូបភាព</b>ដែលអ្នកចង់បម្លែងទៅជា URL (link ថេរ អាចចែករំលែកបាន)")
    bot.register_next_step_handler(msg, _process_img_url_photo)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_OCR)
def btn_ocr(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    msg = bot.reply_to(message, "📝 សូមផ្ញើ<b>រូបភាព</b>ដែលមានអក្សរ ខ្ញុំនឹង Copy អក្សរនោះចេញឲ្យ (ខ្មែរ/អង់គ្លេស)")
    bot.register_next_step_handler(msg, _process_ocr_photo)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == BTN_STATS)
def btn_stats(message):
    cmd_stats(message)


def _extract_image_file_id(message):
    """ត្រឡប់ file_id បើ message ជារូបភាព (photo ឬ image document), បើមិនមែនត្រឡប់ None"""
    if message.content_type == "document":
        mime = (message.document.mime_type or "")
        if not mime.startswith("image/"):
            return None
        return message.document.file_id
    if message.content_type == "photo":
        return message.photo[-1].file_id  # គុណភាពខ្ពស់បំផុត
    return None


def _download_telegram_image(file_id: str) -> Path:
    file_info = bot.get_file(file_id)
    file_bytes = bot.download_file(file_info.file_path)
    in_path = DOWNLOAD_DIR / f"orig_{uuid.uuid4().hex}.jpg"
    in_path.write_bytes(file_bytes)
    return in_path


def _process_enhance_photo(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    file_id = _extract_image_file_id(message)
    if not file_id:
        bot.reply_to(message, "⚠️ សូមផ្ញើជារូបភាព")
        return
    _run_enhance(message, file_id)


def _process_removebg_photo(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    file_id = _extract_image_file_id(message)
    if not file_id:
        bot.reply_to(message, "⚠️ សូមផ្ញើជារូបភាព")
        return
    _run_removebg(message, file_id)


def _process_img_url_photo(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    file_id = _extract_image_file_id(message)
    if not file_id:
        bot.reply_to(message, "⚠️ សូមផ្ញើជារូបភាព")
        return
    _run_img_to_url(message, file_id)


def _process_ocr_photo(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
    file_id = _extract_image_file_id(message)
    if not file_id:
        bot.reply_to(message, "⚠️ សូមផ្ញើជារូបភាព")
        return
    _run_ocr(message, file_id)


def _run_enhance(message, file_id: str):
    if not check_and_consume_quota(message.from_user.id, "enhance"):
        send_quota_exceeded(message.chat.id, message.from_user.id, "enhance")
        return

    status = bot.reply_to(message, "🖼 កំពុងធ្វើឲ្យរូបភាពច្បាស់ សូមរង់ចាំបន្តិច...")
    in_path = out_path = None
    try:
        in_path = _download_telegram_image(file_id)
        out_path = enhance_image(in_path)
        with open(out_path, "rb") as f:
            bot.send_document(
                message.chat.id, f,
                caption="✅ រូបភាពច្បាស់ជាងមុនហើយ!",
                visible_file_name="enhanced.jpg",
            )
        record_event(message.from_user.id, "enhance")
        bot.delete_message(message.chat.id, status.message_id)
    except Exception:
        log.exception("enhance failed")
        bot.edit_message_text("❌ ធ្វើឲ្យរូបភាពច្បាស់មិនបានទេ សូមព្យាយាមម្តងទៀត",
                               message.chat.id, status.message_id)
    finally:
        if in_path:
            cleanup_file(in_path, delay=5)
        if out_path:
            cleanup_file(out_path, delay=20)


def _run_removebg(message, file_id: str):
    if not check_and_consume_quota(message.from_user.id, "removebg"):
        send_quota_exceeded(message.chat.id, message.from_user.id, "removebg")
        return

    status = bot.reply_to(message, "✂️ កំពុងកាត់ផ្ទៃខាងក្រោយ សូមរង់ចាំបន្តិច "
                                    "(ครั้งដំបូងអាចយូរជាងគេ ព្រោះកំពុង download model)...")
    in_path = out_path = None
    try:
        in_path = _download_telegram_image(file_id)
        out_path = remove_background(in_path)
        with open(out_path, "rb") as f:
            bot.send_document(
                message.chat.id, f,
                caption="✅ បានកាត់ផ្ទៃខាងក្រោយចេញ! (PNG ថ្លា)",
                visible_file_name="no_background.png",
            )
        record_event(message.from_user.id, "removebg")
        bot.delete_message(message.chat.id, status.message_id)
    except Exception:
        log.exception("remove background failed")
        bot.edit_message_text("❌ កាត់ផ្ទៃខាងក្រោយមិនបានទេ សូមព្យាយាមម្តងទៀត",
                               message.chat.id, status.message_id)
    finally:
        if in_path:
            cleanup_file(in_path, delay=5)
        if out_path:
            cleanup_file(out_path, delay=20)


def _run_img_to_url(message, file_id: str):
    if not check_and_consume_quota(message.from_user.id, "img2url"):
        send_quota_exceeded(message.chat.id, message.from_user.id, "img2url")
        return

    status = bot.reply_to(message, "🔗 កំពុង Upload រូបភាព...")
    in_path = None
    try:
        in_path = _download_telegram_image(file_id)
        url = upload_to_catbox(in_path)
        record_event(message.from_user.id, "img2url")
        bot.edit_message_text(
            f"✅ <b>URL របស់រូបភាព (link ថេរ អាចចែករំលែកបាន)៖</b>\n\n<code>{url}</code>",
            message.chat.id, status.message_id,
        )
    except Exception:
        log.exception("img2url failed")
        bot.edit_message_text("❌ Upload មិនបានទេ សូមព្យាយាមម្តងទៀត",
                               message.chat.id, status.message_id)
    finally:
        if in_path:
            cleanup_file(in_path, delay=5)


def _run_ocr(message, file_id: str):
    if not check_and_consume_quota(message.from_user.id, "ocr"):
        send_quota_exceeded(message.chat.id, message.from_user.id, "ocr")
        return

    status = bot.reply_to(message, "📝 កំពុង Copy អក្សរពីរូបភាព...")
    in_path = None
    try:
        in_path = _download_telegram_image(file_id)
        text = extract_text_from_image(in_path)
        record_event(message.from_user.id, "ocr")

        if not text:
            bot.edit_message_text("😕 រកមិនឃើញអក្សរនៅក្នុងរូបភាពនេះទេ",
                                   message.chat.id, status.message_id)
        elif len(text) > 3500:
            # អត្ថបទវែងពេក - ផ្ញើជា .txt file ជំនួសឲ្យ message
            txt_path = DOWNLOAD_DIR / f"ocr_{uuid.uuid4().hex}.txt"
            txt_path.write_text(text, encoding="utf-8")
            with open(txt_path, "rb") as f:
                bot.send_document(
                    message.chat.id, f,
                    caption="📝 អត្ថបទដែលបាន Copy (វែងពេក ផ្ញើជា file)",
                    visible_file_name="extracted_text.txt",
                )
            cleanup_file(txt_path, delay=20)
            bot.delete_message(message.chat.id, status.message_id)
        else:
            safe_text = html.escape(text)
            bot.edit_message_text(
                f"📝 <b>អត្ថបទដែលបាន Copy៖</b>\n\n<code>{safe_text}</code>",
                message.chat.id, status.message_id,
            )
    except Exception:
        log.exception("ocr failed")
        bot.edit_message_text("❌ Copy អក្សរមិនបានទេ សូមព្យាយាមម្តងទៀត",
                               message.chat.id, status.message_id)
    finally:
        if in_path:
            cleanup_file(in_path, delay=5)


@bot.message_handler(content_types=["photo", "document"])
def handle_photo(message):
    """ព្រម​ន​ចុចប៊ូតុងមុន: ផ្ញើរូបភាពផ្ទាល់ = default ធ្វើឲ្យច្បាស់ (enhance)"""
    file_id = _extract_image_file_id(message)
    if not file_id:
        return  # document មិនមែនរូបភាព - មិនចាត់ចែង

    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return

    _run_enhance(message, file_id)


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
    users = load_users()
    uid = str(message.from_user.id)
    my_stat = stats["users"].get(uid, {})
    my_user = users.get(uid, {})
    lines = ["📊 <b>ស្ថិតិរបស់អ្នក</b>"]
    for kind, label in _KIND_LABELS.items():
        lines.append(f"{label}៖ {my_stat.get(kind, 0)} ដង")
    lines.append("")
    lines.append(f"⭐ សិទ្ធិប្រើបន្ថែម (bonus)៖ {my_user.get('bonus_credits', 0)} ដង")
    lines.append(f"👥 មិត្តណែនាំចូលរួម៖ {my_user.get('referral_count', 0)} នាក់")
    lines.append("(ប្រើ /referral ដើម្បីទទួល link ណែនាំមិត្ត)")
    lines.append("")
    lines.append("📈 <b>ស្ថិតិសរុប Bot</b>")
    for kind, label in _KIND_LABELS.items():
        lines.append(f"{label}សរុប៖ {stats.get(f'total_{kind}', 0)}")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["tts"])
def cmd_tts(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return
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
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "🔒 សូមចូលរួម Channel មុនប្រើមុខងារនេះ", show_alert=True)
        send_force_sub_prompt(call.message.chat.id)
        return

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

    if not check_and_consume_quota(call.from_user.id, "tts"):
        bot.answer_callback_query(call.id, "⏳ អស់ចំណុះប្រើប្រាស់", show_alert=True)
        send_quota_exceeded(call.message.chat.id, call.from_user.id, "tts")
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
                      and m.text not in (BTN_SEARCH, BTN_TTS, BTN_ENHANCE, BTN_REMOVE_BG, BTN_IMG_URL, BTN_OCR, BTN_STATS))
def handle_search(message):
    if not is_subscribed(message.from_user.id):
        send_force_sub_prompt(message.chat.id)
        return

    query = message.text.strip()
    if len(query) < 2:
        bot.reply_to(message, "⚠️ សូមវាយចំណងជើងឲ្យបានច្បាស់លាស់ជាងនេះ")
        return

    if not check_and_consume_quota(message.from_user.id, "search"):
        send_quota_exceeded(message.chat.id, message.from_user.id, "search")
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
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "🔒 សូមចូលរួម Channel មុនប្រើមុខងារនេះ", show_alert=True)
        send_force_sub_prompt(call.message.chat.id)
        return

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
