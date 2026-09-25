import requests
import time
import json
import os
import base64
import hashlib
import shutil
import uuid
import threading
import random
import re
import html
import pyotp
import csv
import io
import zipfile
import copy
import unicodedata
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import Counter 
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# ==========================================
# ==========================================
# PREMIUM LOADING EMOJIS
# ==========================================
GET_NUMBER_EMOJI_ID = "5319164022245832659"
LOADING_EMOJI_ID = "5316698440434989602"
LANGUAGE_EMOJI_ID = "6071096140168696563"
RESTART_EMOJI_ID = "5355051922862653659"
NUMBER_SUCCESS_EMOJI_ID = "6109396974887247398"

# Keep both loading stages on the requested loading emoji. This guarantees
# that every visible loading state starts with the same premium emoji.
EMOJI_1 = LOADING_EMOJI_ID
EMOJI_2 = LOADING_EMOJI_ID

def loading_html(text):
    """Prefix any loading message with the requested premium emoji."""
    return f'<tg-emoji emoji-id="{LOADING_EMOJI_ID}">⏳</tg-emoji> {text}'

def show_loading(chat_id, msg_id=None):
    import time
    
    if not msg_id:
        # 1st: ইমোজি + Fetching number...
        msg = send_message(chat_id, render_body_text(loading_html("<b>Fetching number...</b>")))
        msg_id = msg.get("result", {}).get("message_id")
    
    # 2nd: শুধু ইমোজি অ্যানিমেশন
    for frame in ["⟳", "◐", "◑", "◒", "◓", "⟳", "✨"]:
        time.sleep(0.3)
        try:
            edit_message(chat_id, msg_id, render_body_text(
                f'<tg-emoji emoji-id="{LOADING_EMOJI_ID}">{frame}</tg-emoji>'
            ))
        except:
            pass
    
    return msg_id


def start_premium_reveal(chat_id, old_msg_id=None):
    """Do not show the old single-emoji reveal animation.

    The old flow sent a standalone custom emoji when the fetching text was
    unavailable.  That made users see one unexplained emoji, so the fetching
    message is now the only loading indicator.
    """
    return None, time.monotonic()


def finish_premium_reveal(chat_id, reveal_id, reveal_started_at,
                           minimum_duration=3.0):
    """Compatibility no-op for the removed single-emoji reveal."""
    return


def start_fetching_loading(chat_id):
    """Show the old Fetching number loading message as a real custom emoji."""
    text = "⏳ Fetching number..."
    result = api_call("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "entities": [
            {
                "type": "custom_emoji",
                "offset": 0,
                "length": 1,
                "custom_emoji_id": LOADING_EMOJI_ID
            },
            {
                "type": "bold",
                "offset": 2,
                "length": 18
            }
        ],
        "disable_web_page_preview": True
    })
    if result and result.get("ok") and result.get("result"):
        return result.get("result", {}).get("message_id"), time.monotonic()

    # Keep the first loading stage visible even on clients/API versions that
    # reject the custom entity.
    fallback = api_call("sendMessage", {
        "chat_id": chat_id,
        "text": "⏳ Fetching number...",
        "disable_web_page_preview": True
    })
    return (
        fallback.get("result", {}).get("message_id") if fallback else None,
        time.monotonic()
    )


def finish_fetching_loading(chat_id, loading_id, started_at,
                            minimum_duration=2.0):
    """Keep Fetching number visible for at least 2 seconds, then remove it."""
    try:
        remaining = minimum_duration - (time.monotonic() - started_at)
        if remaining > 0:
            time.sleep(remaining)
        if loading_id:
            delete_message(chat_id, loading_id)
    except Exception:
        pass


def finish_combined_loading(chat_id, fetching_id, reveal_id,
                            reveal_started_at, minimum_duration=3.0):
    """Remove the fetching message after number selection finishes."""
    try:
        if fetching_id:
            delete_message(chat_id, fetching_id)
    except Exception:
        pass
# Configuration (Token & Owner ID)
# ==========================================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}/"

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "6477114877"))
except ValueError:
    OWNER_ID = 6477114877


def _env_int_list(*names):
    """Read comma/space separated Telegram IDs from environment variables."""
    values = []
    for name in names:
        raw = os.getenv(name, "")
        for item in re.split(r"[\s,;]+", str(raw or "").strip()):
            if item and re.fullmatch(r"-?\d+", item):
                values.append(int(item))
    return list(dict.fromkeys(values))


# OWNER_ID remains the emergency owner. ADMIN_ID/ADMIN_IDS can add one or more
# admin accounts without editing the source code or restoring old settings.
CONFIGURED_ADMIN_IDS = _env_int_list("ADMIN_ID", "ADMIN_IDS")
ALL_ADMIN_IDS = list(dict.fromkeys([OWNER_ID] + CONFIGURED_ADMIN_IDS))
BOT_USERNAME = os.getenv("BOT_USERNAME", "@GX_OTP_V1_BOT")
GOOGLE_SHEET_ID = (os.getenv("GOOGLE_SHEET_ID") or os.getenv("SHEET_ID") or "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = (
    os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    or os.getenv("GOOGLE_SERVICE_ACCOUNT")
    or os.getenv("GOOGLE_CREDENTIALS_JSON")
    or ""
).strip()
try:
    GOOGLE_SYNC_INTERVAL = max(5.0, float(os.getenv("GOOGLE_SYNC_INTERVAL", "10")))
except (TypeError, ValueError):
    GOOGLE_SYNC_INTERVAL = 10.0

if ZoneInfo:
    try:
        DATA_TZ = ZoneInfo("Asia/Dhaka")
    except Exception:
        DATA_TZ = timezone.utc
else:
    DATA_TZ = timezone.utc


def data_now():
    return datetime.now(DATA_TZ)


def data_month_key():
    return data_now().strftime("%Y-%m")


def iso_now():
    return data_now().isoformat(timespec="seconds")

# ==========================================
# Premium Emoji Database
# ==========================================
PEM = {
    "ok": '<tg-emoji emoji-id="5352694861990501856">✅</tg-emoji>',
    "no": '<tg-emoji emoji-id="5420130255174145507">❌</tg-emoji>',
    "warn": '<tg-emoji emoji-id="5336944168944047463">⚠️</tg-emoji>',
    "admin": '<tg-emoji emoji-id="5353032893096567467">📊</tg-emoji>',
    "user": '<tg-emoji emoji-id="5352861489541714456">👤</tg-emoji>',
    "file": '<tg-emoji emoji-id="5352721946054268944">📁</tg-emoji>',
    "rocket": '<tg-emoji emoji-id="5352597830089347330">🚀</tg-emoji>',
    "graph": '<tg-emoji emoji-id="5352877703043258544">📊</tg-emoji>',
    "money": '<tg-emoji emoji-id="5348469219761626211">💸</tg-emoji>',
    "gift": '<tg-emoji emoji-id="5420396762189831222">🎁</tg-emoji>',
    "msg": '<tg-emoji emoji-id="5337302974806922068">💬</tg-emoji>',
    "gear": '<tg-emoji emoji-id="5420155432272438703">⚙️</tg-emoji>',
    "link": '<tg-emoji emoji-id="5420517437885943844">🔗</tg-emoji>',
    "trash": '<tg-emoji emoji-id="5422557736330106570">🗑</tg-emoji>',
    "upload": '<tg-emoji emoji-id="5353001161878182134">📤</tg-emoji>',
    "world": '<tg-emoji emoji-id="5336972142066047577">🌐</tg-emoji>',
    "lock": '<tg-emoji emoji-id="5353022963132174959">🔐</tg-emoji>',
    "phone": '<tg-emoji emoji-id="5337132498965010628">📱</tg-emoji>',
    "num": '<tg-emoji emoji-id="5352862640592949843">🔢</tg-emoji>',
    "pin": '<tg-emoji emoji-id="5352922460897452503">📍</tg-emoji>',
    "star": '<tg-emoji emoji-id="5352552689983067014">✨</tg-emoji>',
    "hi": '<tg-emoji emoji-id="5353027129250453493">👋</tg-emoji>'
}

GLOBAL_BODY_EMOJIS = {
    "➖": "5870818207383686839", "🚫": "5334807341109908955", "😒": "5334763399299506604",
    "🖥": "5334880948259427772", "🌐": "5334590977837403844", "🌟": "5337102391244263212",
    "🕓": "5336983442125001376", "⌛": "5337172996211648018", "💬": "5337302974806922068",
    "🔐": "5337255927735163754", "🍏": "5337132498965010628", "❔": "5336850036145823599",
    "⚠️": "5336944168944047463", "🔥": "5337267511261960341", "💸": "5348469219761626211",
    "🥚": "5348390922507817684", "👨‍⚖": "5334763399299506604", "🐁": "5348494358205207761",
    "🧻": "5348486915026884464", "⚗": "5346311574221000149", "🛴": "5348075478634766440",
    "📊": "5353032893096567467", "🔢": "5352862640592949843", "👤": "5352861489541714456",
    "📁": "5352721946054268944", "🚀": "5352597830089347330", "💎": "5352838545826420397",
    "📍": "5352922460897452503", "👋": "5353027129250453493", "✅": "5352694861990501856",
    "1️⃣": "5352651766288652742", "2️⃣": "5355186458418257716", "3️⃣": "5352867219028091093",
    "4️⃣": "5352566657216714037", "5️⃣": "5353086880835474989", "6️⃣": "5354859211975071385",
    "7️⃣": "5352859127309707652", "8️⃣": "5352957533600389988", "9️⃣": "5353060913463204207",
    "🔤": "5352727417842606016", "📣": "5352980533150259581", "📤": "5353001161878182134",
    "✨": "5352552689983067014", "🔹": "5352638632278660622", "🎙": "5355102594886833928",
    "💴": "5352985330628730418", "📅": "5352585194295564660", "📴": "5352974971167611327",
    "✏️": "5395444784611480792", "📱": "5337132498965010628", "🔗": "5420517437885943844",
    "❌": "5420130255174145507", "⚙️": "5420155432272438703", "🫂": "5420145051336485498",
    "➕": "5420323438508155202", "🗑": "5422557736330106570", "🎁": "5420396762189831222",
    "➤": "5420618897898381296", "🏢": "5420156334215565595", "💳": "5190899075968441286",
    "📝": "5192739271886282680", "🛡": "5190447043545438788", "🤝": "5192805934073685937",
    "💰": "5190576863226933563", "👀": "5190645917711114179", "🕹": "5193100774988617665",
    "🟢": "5192812028632274956", "🧪": "5190781475468915802", "🎨": "5190751148704833975",
    "📂": "5257969839313526622", "🌍": "5780471598922337683", "📌": "5318986077455795572",
    "📢": "5789428375261023681", "🆔": "5352862640592949843", "📈": "5352877703043258544",
    "🔔": "5352980533150259581", "🏦": "5348469219761626211", "🧾": "5192739271886282680",
    "👨‍⚖️": "5334763399299506604", "🔍": "5463352748751753567",
    "🔑": "5197288647275071607"
}

DEFAULT_CUSTOM_MESSAGES = {
    "start": {"text": "╔═══════════╗\n       📊 NUMBER BOT\n╚═══════════╝\n🚀 Welcome to Number & OTP Service\n━━━━━━━━━━━━\n✅ Choose an option below\nto continue using the bot.\n━━━━━━━━━━━━\n💎 Premium OTP Service", "buttons": []},
    "get_number": {"text": f"{PEM['pin']} Select a service:", "buttons": []},
    "select_country": {"text": f"📌 Select a country for {{service}}:", "buttons": []}, 
    "traffic": {"text": f"{PEM['graph']} <b>Traffic Overview</b>\n\n{PEM['ok']} Available Numbers: {{avail}}\n{PEM['rocket']} Assigned Numbers: {{assigned}}", "buttons": []},
    "refer": {"text": f"➖➖➖➖➖➖➖\n« {PEM['gift']} REFER & EARN »\n➖➖➖➖➖➖➖\n{PEM['link']} YOUR LINK:\n<code>{{ref_link}}</code>\n➖➖➖➖➖➖➖\n{PEM['user']} TOTAL REFERS: <b>{{total_ref}}</b>\n➖➖➖➖➖➖➖\n{PEM['money']} PER REFER: <b>{{ref_reward}} TK</b>\n➖➖➖➖➖➖➖", "buttons": []},
    "withdrawal": {"text": "➖➖➖➖➖➖➖\n《 😒 WITHDRAWAL 》\n➖➖➖➖➖➖➖\n👋 Total Otp: {total_otp}\n➖➖➖➖➖➖➖\n🫂 Total Reffer :{total_ref}\n➖➖➖➖➖➖➖\n📅 BALANCE: {bal}৳\n➖➖➖➖➖➖➖\n🔐 MINIMUM: {min_w} ৳\n➖➖➖➖➖➖➖\nSELECT METHOD:", "buttons": []},
    "support": {"text": f"{PEM['msg']} Contact us for any help:", "buttons": []}
}

DEFAULT_PREMIUM_APPS = {
    "FACEBOOK": {"char": "📘", "id": "5296523110734930940", "name": "Facebook"},
    "WHATSAPP": {"char": "💬", "id": "5296439324512918594", "name": "WhatsApp"},
    "TELEGRAM": {"char": "✈️", "id": "5294193228415801857", "name": "Telegram"},
    "WHATSAPP BUSINESSES": {"char": "💼", "id": "5336814486701514414", "name": "WhatsApp Businesses"},
    "IMO": {"char": "💭", "id": "5296393407017556498", "name": "Imo"},
    "INSTAGRAM": {"char": "📸", "id": "5296719399330292238", "name": "Instagram"},
    "APPLE": {"char": "🍎", "id": "5294101883051353361", "name": "Apple"},
    "GOOGLE": {"char": "🔍", "id": "5335010201005231986", "name": "Google"},
    "MICROSOFT": {"char": "🪟", "id": "5334880948259427772", "name": "Microsoft"},
    "OTHER": {"char": "📶", "id": "5305517382138112561", "name": "Other"},
    "TEAMS": {"char": "🧑‍🤝‍🧑", "id": "5334590977837403844", "name": "Teams"},
    "TIKTOK": {"char": "🎵", "id": "5339213256001102461", "name": "Tiktok"},
    "BKASH": {"char": "🏦", "id": "5348469219761626211", "name": "Bkash"},
    "ROCKET": {"char": "🚀", "id": "5346042941196507141", "name": "Rocket"},
    "BYBIT": {"char": "📈", "id": "5348372939479751825", "name": "Bybit"},
    "BINANCE": {"char": "💱", "id": "5348212415077064131", "name": "Binance"},
    "MELBET": {"char": "🌟", "id": "5337102391244263212", "name": "Melbet"},
    "SNAPCHAT": {"char": "👻", "id": "5359441366554255082", "name": "Snapchat"},
    "UBER": {"char": "🚗", "id": "5298715455316303708", "name": "Uber"},
    "PAYPAL": {"char": "💵", "id": "5776103539872896061", "name": "PayPal"},
    "DISCORD": {"char": "🎬", "id": "5116246243646898866", "name": "Discord"},
    "AMAZON": {"char": "🌟", "id": "4995019580536524226", "name": "Amazon"},
    "VIBER": {"char": "💜", "id": "5463060437572528782", "name": "Viber"},
    "LINKEDIN": {"char": "💼", "id": "6224222994265279792", "name": "Linkedin"},
    "LINE": {"char": "🔒", "id": "5399818044866327279", "name": "Line"},
    "WECHAT": {"char": "💜", "id": "5782757599560602950", "name": "Wechat"},
    "TWITTER": {"char": "🐦", "id": "5215726959056662534", "name": "Twitter"},
    "REDDIT": {"char": "👽", "id": "4992421103847604984", "name": "Reddit"},
    "PINTEREST": {"char": "📌", "id": "5346103513120258857", "name": "Pinterest"},
    "TWITCH": {"char": "🎮", "id": "5233333563306301418", "name": "Twitch"},
    "ZOOM": {"char": "📹", "id": "5881799193219043268", "name": "Zoom"},
    "SIGNAL": {"char": "💬", "id": "5293998404404272267", "name": "Signal"},
    "SLACK": {"char": "💻", "id": "4994972469040251302", "name": "Slack"},
    "SKYPE": {"char": "☎️", "id": "4992613535562334989", "name": "Skype"},
    "NETFLIX": {"char": "🎥", "id": "6255738712664050133", "name": "Netflix"},
    "SPOTIFY": {"char": "🎵", "id": "5411392711146095115", "name": "Spotify"},
    "AMAZON PRIME": {"char": "📺", "id": "6111801057061374810", "name": "Amazon Prime"},
    "HOICHOI": {"char": "🍿", "id": "6104822598493801746", "name": "Hoichoi"},
    "DARAZ": {"char": "📦", "id": "5336879280578138635", "name": "Daraz"},
    "FOODPANDA": {"char": "🐼", "id": "5336879280578138635", "name": "Foodpanda"},
    "PATHAO": {"char": "🛵", "id": "5336879280578138635", "name": "Pathao"},
    "ALIEXPRESS": {"char": "🛒", "id": "5336879280578138635", "name": "AliExpress"},
    "SHOPEE": {"char": "🛍️", "id": "5336879280578138635", "name": "Shopee"},
    "PAYONEER": {"char": "💳", "id": "5336879280578138635", "name": "Payoneer"},
    "WISE": {"char": "🦉", "id": "5336879280578138635", "name": "Wise"},
    "CHATGPT": {"char": "🤖", "id": "5296516998996445955", "name": "ChatGPT"},
    "NOTION": {"char": "📓", "id": "5336879280578138635", "name": "Notion"},
    "GITHUB": {"char": "🐙", "id": "5417836094098007862", "name": "GitHub"},
    "CANVA": {"char": "🖌️", "id": "5111661409008092227", "name": "Canva"},
    "FIGMA": {"char": "🎨", "id": "5336879280578138635", "name": "Figma"},
    "UPWORK": {"char": "💼", "id": "5336879280578138635", "name": "Upwork"},
    "FIVERR": {"char": "🟢", "id": "5336879280578138635", "name": "Fiverr"},
    "YAHOO": {"char": "🌐", "id": "5336879280578138635", "name": "Yahoo"},
    "DROPBOX": {"char": "☁️", "id": "5336879280578138635", "name": "Dropbox"},
    "COURSERA": {"char": "📚", "id": "5336879280578138635", "name": "Coursera"},
    "DUOLINGO": {"char": "🗣️", "id": "5336879280578138635", "name": "Duolingo"},
}

# ==========================================
# Disabled legacy database adapter
# ==========================================
# This bot never creates a PostgreSQL connection. The old adapter names below
# are retained only because existing handlers use their increment/timestamp
# sentinels; the active database object is _RuntimeDatabase farther below.
psycopg = None
Jsonb = None
DATABASE_URL = ""
BOT_NAMESPACE = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()[:24] if TOKEN else "unconfigured"


class _PostgresIncrement:
    def __init__(self, amount):
        self.amount = amount


class _PostgresServerTimestamp:
    pass


class _PostgresSentinels:
    Increment = _PostgresIncrement
    SERVER_TIMESTAMP = _PostgresServerTimestamp()


# These names keep the existing bot code readable. They are translated into
# PostgreSQL values by the adapter below.
postgres = _PostgresSentinels()


class _PostgresDocument:
    def __init__(self, document_id, data=None, exists=True):
        self.id = str(document_id)
        self._data = copy.deepcopy(data) if isinstance(data, dict) else {}
        self.exists = bool(exists)

    def to_dict(self):
        return copy.deepcopy(self._data)


def _postgres_value(value, previous=None):
    """Resolve adapter sentinels into JSON-safe PostgreSQL values."""
    if isinstance(value, _PostgresIncrement):
        old_value = previous if isinstance(previous, (int, float)) else 0
        return old_value + value.amount
    if isinstance(value, _PostgresServerTimestamp):
        return iso_now()
    if isinstance(value, dict):
        previous = previous if isinstance(previous, dict) else {}
        return {
            str(key): _postgres_value(item, previous.get(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_postgres_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class _PostgresDocumentReference:
    def __init__(self, database, collection_name, document_id):
        self.database = database
        self.collection_name = str(collection_name)
        self.document_id = str(document_id)

    def get(self):
        with self.database._connect() as connection:
            row = connection.execute(
                """
                SELECT data
                FROM bot_documents
                WHERE namespace = %s AND collection_name = %s AND document_id = %s
                """,
                (self.database.namespace, self.collection_name, self.document_id),
            ).fetchone()
        if not row:
            return _PostgresDocument(self.document_id, {}, exists=False)
        return _PostgresDocument(self.document_id, row[0], exists=True)

    def set(self, data, merge=False):
        if not isinstance(data, dict):
            raise ValueError("PostgreSQL document data must be a dictionary.")
        with self.database._connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    SELECT data
                    FROM bot_documents
                    WHERE namespace = %s AND collection_name = %s AND document_id = %s
                    FOR UPDATE
                    """,
                    (self.database.namespace, self.collection_name, self.document_id),
                ).fetchone()
                existing = row[0] if row else {}
                incoming = _postgres_value(data, existing)
                result = dict(existing) if merge and isinstance(existing, dict) else {}
                result.update(incoming)
                self.database._upsert(connection, self.collection_name, self.document_id, result)
        return None

    def update(self, data):
        if not isinstance(data, dict):
            raise ValueError("PostgreSQL document update must be a dictionary.")
        with self.database._connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    SELECT data
                    FROM bot_documents
                    WHERE namespace = %s AND collection_name = %s AND document_id = %s
                    FOR UPDATE
                    """,
                    (self.database.namespace, self.collection_name, self.document_id),
                ).fetchone()
                if not row:
                    raise KeyError(f"Document does not exist: {self.collection_name}/{self.document_id}")
                existing = row[0] if isinstance(row[0], dict) else {}
                result = dict(existing)
                result.update(_postgres_value(data, existing))
                self.database._upsert(connection, self.collection_name, self.document_id, result)
        return None

    def delete(self):
        with self.database._connect() as connection:
            connection.execute(
                """
                DELETE FROM bot_documents
                WHERE namespace = %s AND collection_name = %s AND document_id = %s
                """,
                (self.database.namespace, self.collection_name, self.document_id),
            )


class _PostgresCollection:
    def __init__(self, database, collection_name):
        self.database = database
        self.collection_name = str(collection_name)
        self._order_field = None
        self._descending = False
        self._limit = None

    def document(self, document_id):
        return _PostgresDocumentReference(self.database, self.collection_name, document_id)

    def order_by(self, field, direction="ASCENDING"):
        self._order_field = str(field)
        self._descending = str(direction).upper() == "DESCENDING"
        return self

    def limit(self, count):
        self._limit = max(0, int(count))
        return self

    def select(self, _fields):
        # The bot uses select([]) only to cheaply enumerate document IDs.
        return self

    def stream(self):
        with self.database._connect() as connection:
            rows = connection.execute(
                """
                SELECT document_id, data
                FROM bot_documents
                WHERE namespace = %s AND collection_name = %s
                """,
                (self.database.namespace, self.collection_name),
            ).fetchall()

        if self._order_field:
            def sort_key(row):
                value = (row[1] or {}).get(self._order_field)
                if value is None:
                    return (0, "")
                if isinstance(value, (int, float)):
                    return (1, value)
                return (1, str(value))
            rows.sort(key=sort_key, reverse=self._descending)
        if self._limit is not None:
            rows = rows[:self._limit]
        return iter(_PostgresDocument(document_id, data) for document_id, data in rows)


class _PostgresDatabase:
    def __init__(self, database_url, namespace):
        if not psycopg or not Jsonb:
            raise RuntimeError(
                "The legacy database adapter is disabled. Use Google Sheets."
            )
        if not database_url:
            raise RuntimeError(
                "A legacy database adapter was requested, but only Google Sheets is supported."
            )
        self.database_url = database_url
        self.namespace = namespace
        self._lock = threading.RLock()
        self._ensure_schema()

    def __bool__(self):
        return True

    def _connect(self):
        raise RuntimeError(
            "The legacy database adapter is disabled. Use Google Sheets."
        )

    def _ensure_schema(self):
        raise RuntimeError(
            "The legacy database adapter is disabled. Use Google Sheets."
        )

    def _upsert(self, connection, collection_name, document_id, data):
        connection.execute(
            """
            INSERT INTO bot_documents
                (namespace, collection_name, document_id, data, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (namespace, collection_name, document_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
            """,
            (
                self.namespace,
                str(collection_name),
                str(document_id),
                Jsonb(data),
            ),
        )

    def collection(self, name):
        return _PostgresCollection(self, name)


class _PostgresConnectionContext:
    """Release the adapter lock when a psycopg connection context closes."""
    def __init__(self, connection, lock):
        self.connection = connection
        self.lock = lock

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            self.connection.close()
            self.lock.release()
        return False


# The bot intentionally has no persistent database.  This small compatibility
# store keeps the existing handlers simple while the process is running; it is
# never written to Render's filesystem or to PostgreSQL.  The user/financial
# collections are loaded from and mirrored back to Google Sheets.
_runtime_collections = {
    "users": {},
    "history": {},
    "withdrawals": {},
    "settings": {},
}
_runtime_store_lock = threading.RLock()


class _RuntimeDocument:
    def __init__(self, document_id, data=None, exists=True):
        self.id = str(document_id)
        self._data = copy.deepcopy(data) if isinstance(data, dict) else {}
        self.exists = bool(exists)

    def to_dict(self):
        return copy.deepcopy(self._data)


class _RuntimeDocumentReference:
    def __init__(self, collection_name, document_id):
        self.collection_name = str(collection_name)
        self.document_id = str(document_id)

    def get(self):
        with _runtime_store_lock:
            data = _runtime_collections.setdefault(self.collection_name, {}).get(self.document_id)
            if data is None:
                return _RuntimeDocument(self.document_id, {}, exists=False)
            return _RuntimeDocument(self.document_id, data, exists=True)

    def set(self, data, merge=False):
        if not isinstance(data, dict):
            raise ValueError("Runtime document data must be a dictionary.")
        with _runtime_store_lock:
            collection = _runtime_collections.setdefault(self.collection_name, {})
            existing = collection.get(self.document_id, {})
            incoming = _postgres_value(data, existing)
            result = dict(existing) if merge and isinstance(existing, dict) else {}
            result.update(incoming)
            collection[self.document_id] = copy.deepcopy(result)

    def update(self, data):
        if not isinstance(data, dict):
            raise ValueError("Runtime document update must be a dictionary.")
        with _runtime_store_lock:
            collection = _runtime_collections.setdefault(self.collection_name, {})
            if self.document_id not in collection:
                raise KeyError(f"Document does not exist: {self.collection_name}/{self.document_id}")
            existing = collection[self.document_id]
            result = dict(existing)
            result.update(_postgres_value(data, existing))
            collection[self.document_id] = copy.deepcopy(result)

    def delete(self):
        with _runtime_store_lock:
            _runtime_collections.setdefault(self.collection_name, {}).pop(self.document_id, None)


class _RuntimeCollection:
    def __init__(self, collection_name):
        self.collection_name = str(collection_name)
        self._order_field = None
        self._descending = False
        self._limit = None

    def document(self, document_id):
        return _RuntimeDocumentReference(self.collection_name, document_id)

    def order_by(self, field, direction="ASCENDING"):
        self._order_field = str(field)
        self._descending = str(direction).upper() == "DESCENDING"
        return self

    def limit(self, count):
        self._limit = max(0, int(count))
        return self

    def select(self, _fields):
        return self

    def stream(self):
        with _runtime_store_lock:
            rows = list(_runtime_collections.setdefault(self.collection_name, {}).items())
        if self._order_field:
            def sort_key(row):
                value = (row[1] or {}).get(self._order_field)
                if value is None:
                    return (0, "")
                if isinstance(value, (int, float)):
                    return (1, value)
                return (1, str(value))
            rows.sort(key=sort_key, reverse=self._descending)
        if self._limit is not None:
            rows = rows[:self._limit]
        return iter(_RuntimeDocument(document_id, data) for document_id, data in rows)


class _RuntimeDatabase:
    def __bool__(self):
        return True

    def collection(self, name):
        return _RuntimeCollection(name)


db = _RuntimeDatabase()
print("✅ Runtime-only storage ready; Google Sheets is the persistent data source.")

bot_settings = {
    "admins": ALL_ADMIN_IDS.copy(),
    "panels": [], 
    "fw_groups": [], 
    "otp_link": "https://t.me/your_otp_group",
    "withdraw_on": True,
    "join_notifications": {str(OWNER_ID): True},
    "min_withdraw": 30.0,
    "otp_reward": 0.1,
    "refer_reward": 0.2,
    "cooldown": 10,
    "num_req": 3,
    "num_share": 1, 
    "support_link": "https://t.me/your_support",
    "w_methods": ["bKash", "Nagad"],
    "w_group": "", 
    
    "fj_on": False,
    "fj_channels": [], 
    "stex_keys": [], 
    "voltx_keys": [],
    "zenex_keys": [],
    "search_countries": [],
    "voltx_search_countries": [],
    "zenex_search_countries": [],
    "stex_services": {},
    "voltx_services": {},
    "zenex_services": {},
    "premium_flags": {
        "1": {"char": "🇺🇸", "iso": "US", "name": "United States", "id": "5913463998522592692"},
        "880": {"char": "🇧🇩", "iso": "BD", "name": "Bangladesh", "id": "5911365056594973179"},
        "91": {"char": "🇮🇳", "iso": "IN", "name": "India", "id": "5913754823643107921"},
        "92": {"char": "🇵🇰", "iso": "PK", "name": "Pakistan", "id": "5913705895375672082"},
        "44": {"char": "🇬🇧", "iso": "GB", "name": "United Kingdom", "id": "5913443365499703513"}
    },
    "premium_apps": copy.deepcopy(DEFAULT_PREMIUM_APPS),
    "custom_messages": copy.deepcopy(DEFAULT_CUSTOM_MESSAGES)
}

# Google Sheets stores only values that differ from this clean runtime
# baseline.  The runtime still has safe defaults, but a new/empty sheet never
# receives placeholder links, sample text, bundled emoji data, or other demo
# values just because the process started.
DEFAULT_BOT_SETTINGS = copy.deepcopy(bot_settings)

def ensure_premium_apps():
    """Add bundled app icons without removing admin-added custom apps."""
    apps = bot_settings.setdefault("premium_apps", {})
    legacy_ids = {"5334807341109908955", "5334759662677957452"}
    for app_key, app_data in DEFAULT_PREMIUM_APPS.items():
        current = apps.get(app_key)
        if not current or current.get("id") in legacy_ids or current.get("char") == "🚫":
            apps[app_key] = copy.deepcopy(app_data)

FS_KEYS = [
    "admins", "panels", "fw_groups", "otp_link", "withdraw_on", 
    "min_withdraw", "otp_reward", "refer_reward", "cooldown", 
    "num_req", "num_share", "support_link", "w_methods", "w_group", "stex_keys", "voltx_keys", "search_countries", "stex_services", "voltx_services",
    "fj_on", "fj_channels", "join_notifications", "voltx_auto", "stex_auto", "zenex_auto", "zenex_keys", "zenex_services", "zenex_search_countries"
]

number_batches = {}
used_numbers_list = []
stex_assigned_numbers = {} 
voltx_assigned_numbers = {}
zenex_assigned_numbers = {}
# Number allocation is shared by Telegram update workers and the provider
# listeners.  Keep the claim set in memory only: numbers are operational
# state, not user/financial data, so they must never be written to Sheets.
number_allocation_lock = threading.RLock()
claimed_numbers = set()
STEX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"
VOLTX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tnevs/@public/api"
ZENEX_BASE_URL = "https://api.zenexnetwork.com"
total_uploaded_stats = 0
total_assigned_stats = 0
processed_otps = set() 
recent_traffic = []
user_banned_cache = {}
local_users = {}
audit_history = []
data_month = data_month_key()

google_sync_lock = threading.Lock()
google_sync_trigger_lock = threading.Lock()
google_sync_trigger_scheduled = False
google_sheet_last_signature = None
google_sheet_tabs = set()
google_sheet_last_error = ""
google_sheet_initial_sync = True
database_save_lock = threading.RLock()

# Active HTTP sessions for Auto Captcha Panels
panel_sessions = {}
PANEL_API_REFRESH_INTERVAL = 600.0
panel_api_cache = {}
panel_api_cache_lock = threading.RLock()

def normalize_panel_url(raw_url):
    """Normalize and validate a provider URL before saving it."""
    value = str(raw_url or "").strip()
    if not value:
        raise ValueError("URL cannot be empty.")
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    parsed = urlparse(value)
    if (
        re.search(r"\s", value)
        or parsed.scheme.lower() not in ("http", "https")
        or not parsed.netloc
        or not parsed.hostname
    ):
        raise ValueError("Please send a valid HTTP/HTTPS URL.")
    return value


def panel_api_request_urls(panel):
    """Return the request URL candidates for an API provider.

    A Full API URL is used exactly as supplied (with optional {token}/{key}
    placeholders supported). A base URL keeps the older token/key fallbacks.
    """
    full_url = str(panel.get("full_api_url", "") or "").strip()
    base_url = str(panel.get("api_url", "") or "").strip()
    token = str(panel.get("token", "") or "").strip()

    if full_url:
        try:
            full_url = normalize_panel_url(full_url)
        except ValueError:
            return []
        return [full_url.replace("{token}", token).replace("{key}", token)]

    if not base_url:
        return []
    try:
        base_url = normalize_panel_url(base_url)
    except ValueError:
        return []

    if "{token}" in base_url or "{key}" in base_url:
        return [base_url.replace("{token}", token).replace("{key}", token)]
    if "token=" in base_url.lower() or "key=" in base_url.lower():
        return [base_url]

    separator = "&" if "?" in base_url else "?"
    return [
        f"{base_url}{separator}token={token}",
        f"{base_url}{separator}key={token}&start=0",
        f"{base_url}{separator}key={token}",
    ]


def _panel_number_value(value):
    """Return a real provider number, or None for unrelated numeric fields."""
    if value is None or isinstance(value, (dict, list, tuple)):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 18:
        return None
    # Do not mistake timestamps, ids, counters, or an empty placeholder for a
    # phone number. Values are accepted only when they came from a number-like
    # provider field (the caller enforces that).
    if len(set(digits)) == 1:
        return None
    return digits


PANEL_NUMBER_KEYS = {
    "number", "num", "phone", "phone_number", "phonenumber",
    "msisdn", "mobile", "mobile_number", "mobilenumber",
    "telephone", "tel", "full_number", "national_number",
    "no_plus_number", "receiver", "recipient", "to_number",
}
PANEL_MESSAGE_KEYS = {
    "message", "msg", "sms", "sms_text", "smstext", "content",
    "text", "body", "otp_message",
}
PANEL_SERVICE_KEYS = {
    "service", "app", "application", "site", "platform", "sender",
}


def parse_panel_number_response(response_text, p_config=None):
    """Parse provider JSON into real numbers, including number-only APIs.

    Hadi-like APIs often return available numbers without an SMS message.
    The old parser deliberately required an OTP message, which made those
    providers look empty. This parser accepts only explicit phone-number
    fields; it never manufactures a number from a counter, timestamp, or
    arbitrary JSON value.
    """
    results = []
    seen = set()
    try:
        data = json.loads(response_text)
    except (TypeError, ValueError):
        return results

    def walk(node, inherited_service=""):
        if isinstance(node, dict):
            lower = {
                re.sub(r"[^a-z0-9_]", "_", str(key).lower()).strip("_"): value
                for key, value in node.items()
            }
            service = inherited_service
            for key in PANEL_SERVICE_KEYS:
                if lower.get(key) not in (None, ""):
                    service = str(lower[key]).strip()
                    break

            number = None
            for key in PANEL_NUMBER_KEYS:
                if key in lower:
                    number = _panel_number_value(lower[key])
                    if number:
                        break
            if number and number not in seen:
                message = ""
                for key in PANEL_MESSAGE_KEYS:
                    if lower.get(key) not in (None, ""):
                        message = str(lower[key]).strip()
                        break
                otp = extract_otp_code(message) if message else None
                item = {
                    "number": number,
                    "message": message,
                    "service": service,
                }
                if otp:
                    item["otp"] = otp
                seen.add(number)
                results.append(item)

            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, service)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value, inherited_service)

    walk(data)
    return results


def fetch_api_panel_data(panel, timeout=15):
    """Fetch one API panel without inventing fallback data.

    Returns (otp_rows, number_rows, status_text). The first non-error response
    wins. A successful response with no recognized records is reported clearly
    so the admin can fix the provider's response/URL instead of seeing silence.
    """
    urls = panel_api_request_urls(panel)
    if not urls:
        return [], [], "Invalid API URL"
    headers = {
        "User-Agent": "GX-Number-Bot/1.0",
        "Accept": "application/json,text/plain,text/html;q=0.9,*/*;q=0.8",
    }
    last_status = "No response"
    for request_url in urls:
        try:
            response = requests.get(request_url, headers=headers, timeout=timeout)
            last_status = f"HTTP {response.status_code}"
            if not response.ok:
                continue
            raw_text = response.text or ""
            number_rows = parse_panel_number_response(raw_text, panel)
            otp_rows = parse_panel_response(raw_text, panel)
            if otp_rows:
                return otp_rows, number_rows, "OK"
            if number_rows:
                return [], number_rows, "OK"
            # A valid HTTP response is still useful feedback even when its
            # schema is unsupported; do not silently try to invent records.
            if raw_text.strip():
                return [], [], "HTTP 200: no number/message records recognized"
        except requests.RequestException as exc:
            last_status = f"Request error: {str(exc)[:80]}"
        except Exception as exc:
            last_status = f"Parse error: {str(exc)[:80]}"
    return [], [], last_status


# 🌟 sAjaxSource (AJAX/DataTable) এবং Fallback HTML Parser Helper Function
def fetch_cpt_panel_cdrs(p, session, check_url):
    res = session.get(check_url, timeout=15)
    html_text = res.text
    
    # সেশন শেষ হয়েছে বা লগইন পেজে রিডাইরেক্ট করেছে কি না তা চেক করা
    final_url = str(getattr(res, "url", "") or "").lower()
    login_redirect = bool(re.search(r"/(?:login|signin)(?:\.php)?(?:[/?#]|$)", final_url))
    login_markers = (
        "sign in to your account",
        "please sign in",
        "welcome back!",
    )
    if login_redirect or any(marker in html_text.lower() for marker in login_markers):
        raise Exception("Session expired")
        
    soup = BeautifulSoup(html_text, 'html.parser')
    s_ajax_source = ""
    for script in soup.find_all("script"):
        script_text = script.string or ""
        match = re.search(r'sAjaxSource":\s*"([^"]+)"', script_text)
        if match:
            s_ajax_source = match.group(1)
            break
            
    results = []
    
    n_col_name = p.get("num_col_name", "number").lower()
    m_col_name = p.get("msg_col_name", "message").lower()
    n_idx = int(p.get("num_col_idx", 1)) - 1 if p.get("num_col_idx") else 1
    m_idx = int(p.get("msg_col_idx", 2)) - 1 if p.get("msg_col_idx") else 2

    # ৫.১ যদি sAjaxSource AJAX লিংক পাওয়া যায়
    if s_ajax_source:
        baseUrl = p.get("login_url", "").split("/client")[0].split("/login")[0].strip()
        if not baseUrl.startswith("http"):
            baseUrl = "http://" + baseUrl
            
        full_ajax_url = ""
        if s_ajax_source.startswith("http"):
            full_ajax_url = s_ajax_source
        elif s_ajax_source.startswith("/"):
            full_ajax_url = f"{baseUrl}{s_ajax_source}"
        else:
            last_slash_idx = check_url.rfind("/")
            current_dir = check_url[:last_slash_idx]
            full_ajax_url = f"{current_dir}/{s_ajax_source}"

        if "iDisplayLength" not in full_ajax_url:
            # Respect the panel record setting and cap an unlimited request.
            # Fetching 10,000 rows every monitor cycle wastes bandwidth.
            try:
                record_limit = int(p.get("records", 0))
            except (TypeError, ValueError):
                record_limit = 0
            record_limit = 1000 if record_limit <= 0 else min(record_limit, 1000)
            query_params = (
                "sEcho=1&iColumns=7&iDisplayStart=0"
                f"&iDisplayLength={record_limit}"
                "&sSearch=&iSortingCols=1&iSortCol_0=0&sSortDir_0=desc"
            )
            divider = "&" if "?" in full_ajax_url else "?"
            full_ajax_url += f"{divider}{query_params}"

        ajax_headers = {
            "Referer": check_url,
            "X-Requested-With": "XMLHttpRequest"
        }
        
        ajax_res = session.get(full_ajax_url, headers=ajax_headers, timeout=15)
        data_dict = ajax_res.json()
        rows = data_dict.get("aaData", [])
        for row_val in rows:
            if not isinstance(row_val, list):
                continue
                
            if len(row_val) < max(n_idx, m_idx) + 1:
                continue
                
            num_val = row_val[n_idx] if (0 <= n_idx < len(row_val)) else row_val[2]
            msg_val = row_val[m_idx] if (0 <= m_idx < len(row_val)) else row_val[4]
            
            clean_num = re.sub(r'\D', '', str(num_val))
            if clean_num and 5 <= len(clean_num) <= 18:
                otp = extract_otp_code(msg_val)
                if otp and len(msg_val) > 4:
                    results.append({"number": clean_num, "message": msg_val, "otp": otp})
                    
    else:
        # ৫.২ ডাইরেক্ট HTML টেবিল থেকে রিড করার ব্যাকআপ লজিক
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            if not rows: continue
            
            final_n_idx = n_idx
            final_m_idx = m_idx
            
            header_cells = rows[0].find_all(['th', 'td'])
            for i, cell in enumerate(header_cells):
                c_text = cell.get_text(strip=True).lower()
                if n_col_name in c_text: final_n_idx = i
                if m_col_name in c_text: final_m_idx = i

            for row in rows:
                cols = row.find_all(['td', 'th'])
                if all(c.name == 'th' for c in cols): continue
                
                if len(cols) > max(final_n_idx, final_m_idx):
                    num_text = cols[final_n_idx].get_text(separator=" ", strip=True)
                    msg_text = cols[final_m_idx].get_text(separator=" ", strip=True)
                    
                    clean_num = re.sub(r'\D', '', num_text)
                    if clean_num and 5 <= len(clean_num) <= 18:
                        otp = extract_otp_code(msg_text)
                        if otp and len(msg_text) > 4:
                            results.append({"number": clean_num, "message": msg_text, "otp": otp})
                            
    return results, html_text

# Track active number sessions to expire them automatically
user_active_sessions = {}

assigned_number_rates = {}

def load_db():
    global bot_settings, number_batches, used_numbers_list, total_uploaded_stats, total_assigned_stats, recent_traffic, stex_assigned_numbers, voltx_assigned_numbers, zenex_assigned_numbers, processed_otps, assigned_number_rates, local_users, audit_history, data_month, claimed_numbers
    # Settings, number stock, provider keys and runtime caches deliberately
    # reset on process restart.  Only users, financial events and withdrawals
    # are restored from Google Sheets in main().
    ensure_premium_apps()
    with number_allocation_lock:
        claimed_numbers.clear()
    # SEARCH NUMBER was removed from the product.  Remove any old saved menu
    # block so a previous token's configuration cannot show it again.
    bot_settings.setdefault("custom_messages", {}).pop("search_number", None)
    if not isinstance(bot_settings.get("panels"), list):
        bot_settings["panels"] = []
    for panel in bot_settings["panels"]:
        if not isinstance(panel, dict):
            continue
        panel.setdefault("type", "API Panel")
        panel.setdefault("status", "OFF")
        panel.setdefault("name", "Unnamed Provider")
        panel.setdefault("api_url", "")
        panel.setdefault("full_api_url", "")
        panel.setdefault("token", "")
        panel.setdefault("records", 0)

def save_local_db():
    # Compatibility no-op.  Runtime state is never written to Render's disk.
    return


def save_user_store():
    # Compatibility no-op. Users are mirrored to Google Sheets instead.
    return


def _atomic_json_write(path, value):
    raise RuntimeError("Local JSON persistence is disabled. Use Google Sheets.")

def _sync_fs():
    """Legacy hook kept for compatibility; runtime state is not persisted."""
    return

def save_db():
    # Keep the existing compatibility API. Durable configuration and records
    # are written only through the four Google Sheets tabs below.
    if "_deduplicate_bot_settings" in globals():
        global bot_settings
        bot_settings = _deduplicate_bot_settings(bot_settings)
    # Persist only the durable admin configuration to Google Sheets. Number
    # claims, OTP de-duplication caches, traffic, and other live state remain
    # in memory and are intentionally rebuilt after a restart.
    if (
        "trigger_google_sheets_sync" in globals()
        and google_sheets_configured()
        and google_sheet_data_loaded
    ):
        trigger_google_sheets_sync()


# ==========================================
# Google Sheets persistent user/financial data
# ==========================================
# Configure GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON as environment
# variables. The service account must have Editor access to the spreadsheet.
# Users, financial records, and the durable admin configuration are persistent
# in these Google Sheets tabs. Number claims, live sessions, provider HTTP
# sessions, traffic, and OTP de-duplication caches stay runtime-only.
GOOGLE_SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_SHEET_NAMES = ["Users", "Withdrawals", "History", "BotConfig"]
GOOGLE_SHEET_LEGACY_NAMES = {"RuntimeState"}
GOOGLE_SHEET_HEADERS = {
    "Users": EXPORT_USER_FIELDS if "EXPORT_USER_FIELDS" in globals() else [
        "user_name", "username", "user_id", "balance", "otp",
        "total_refers", "total_otps", "banned", "verified", "language",
        "created_at", "updated_at", "referred_by", "ref_paid"
    ],
    "Withdrawals": [
        "request_id", "user_id", "amount", "method", "number",
        "full_name", "status", "timestamp", "balance_after"
    ],
    "History": [
        "event_id", "timestamp", "user_id", "event_type", "amount",
        "status", "method", "request_id", "balance_after",
        "payment_number", "message"
    ],
    "BotConfig": ["setting", "value_json"],
}
google_auth_warning_printed = False
google_sheet_data_loaded = False
google_sheet_load_error = ""
google_startup_notice_sent = False
google_startup_notice_lock = threading.Lock()


def google_sheets_configured():
    return bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON)


def _read_service_account_info():
    raw = GOOGLE_SERVICE_ACCOUNT_JSON
    if not raw:
        return None
    try:
        if os.path.isfile(raw):
            with open(raw, "r", encoding="utf-8") as handle:
                return json.load(handle)
        if raw.startswith("{"):
            return json.loads(raw)
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON/base64: {exc}")


def _google_access_token():
    """Get a short-lived service-account token without storing credentials."""
    global google_auth_warning_printed
    try:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        if not google_auth_warning_printed:
            print("⚠️ Google Sheets needs the optional google-auth package.")
            google_auth_warning_printed = True
        return None

    info = _read_service_account_info()
    credentials = Credentials.from_service_account_info(info, scopes=GOOGLE_SHEET_SCOPES)
    credentials.refresh(Request())
    return credentials.token


def _google_api(method, url, token, payload=None, params=None):
    response = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        params=params,
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Google Sheets API {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


def _ensure_google_sheet_tabs(token):
    global google_sheet_tabs
    base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}"
    data = _google_api("GET", base_url, token, params={"fields": "sheets.properties"})
    sheet_properties = [
        item.get("properties", {}) for item in data.get("sheets", [])
    ]
    google_sheet_tabs = {
        item.get("title") for item in sheet_properties if item.get("title")
    }
    legacy_sheet_ids = [
        item.get("sheetId")
        for item in sheet_properties
        if item.get("title") in GOOGLE_SHEET_LEGACY_NAMES
        and item.get("sheetId") is not None
    ]
    missing = [name for name in GOOGLE_SHEET_NAMES if name not in google_sheet_tabs]
    if missing:
        _google_api(
            "POST",
            f"{base_url}:batchUpdate",
            token,
            {"requests": [
                {"addSheet": {"properties": {"title": name}}}
                for name in missing
            ]},
        )
        google_sheet_tabs.update(missing)
    # Add the replacement tabs before deleting RuntimeState. Google does not
    # allow deleting the only sheet in a spreadsheet.
    if legacy_sheet_ids:
        _google_api(
            "POST",
            f"{base_url}:batchUpdate",
            token,
            {
                "requests": [
                    {"deleteSheet": {"sheetId": sheet_id}}
                    for sheet_id in legacy_sheet_ids
                ]
            },
        )
        google_sheet_tabs.difference_update(GOOGLE_SHEET_LEGACY_NAMES)


def _json_cell(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return "" if value is None else value


def _google_sheet_rows():
    users, history = collect_export_rows()
    withdrawals = []
    for snapshot in db.collection("withdrawals").order_by(
        "timestamp", direction="DESCENDING"
    ).stream():
        row = snapshot.to_dict()
        row["request_id"] = row.get("request_id", snapshot.id)
        if _is_group_or_channel_record(row):
            continue
        withdrawals.append({
            key: row.get(key, "")
            for key in (
                "request_id", "user_id", "amount", "method", "number",
                "full_name", "status", "timestamp", "balance_after"
            )
        })
    withdrawals = list(_deduplicate_collection_rows(
        withdrawals, "withdrawals"
    ).values())
    history = list(_deduplicate_collection_rows(history, "history").values())
    users = list(_deduplicate_collection_rows(users, "users").values())
    # Keep BotConfig human-readable: one changed setting per row.  Provider
    # panel tokens and URLs are deliberately retained because they are needed
    # to restart the bot without asking the admin to configure every panel
    # again.  Runtime-only number claims, OTP de-duplication caches, traffic,
    # and counters are intentionally not written to Sheets.
    config_rows = []
    clean_settings = _deduplicate_bot_settings(bot_settings)
    for key in sorted(clean_settings):
        value = clean_settings.get(key)
        default_value = DEFAULT_BOT_SETTINGS.get(key, object())
        if value == default_value:
            continue
        if key == "custom_messages" and isinstance(value, dict):
            changed_messages = {}
            default_messages = DEFAULT_BOT_SETTINGS.get("custom_messages", {})
            for message_key, message_value in value.items():
                if message_value != default_messages.get(message_key):
                    changed_messages[message_key] = copy.deepcopy(message_value)
            value = changed_messages
            if not value:
                continue
        config_rows.append({
            "setting": key,
            "value_json": json.dumps(
                copy.deepcopy(value), ensure_ascii=False, default=str
            ),
        })

    return {
        "Users": sorted(users, key=lambda row: str(row.get("user_id", ""))),
        "Withdrawals": sorted(
            withdrawals, key=lambda row: str(row.get("request_id", ""))
        ),
        "History": sorted(
            history, key=lambda row: str(row.get("event_id", ""))
        ),
        "BotConfig": config_rows,
    }


def _sheet_rows(token, sheet_name):
    base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}/values/{sheet_name}"
    data = _google_api("GET", base_url, token)
    values = data.get("values", []) if isinstance(data, dict) else []
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    rows = []
    for raw_row in values[1:]:
        if not any(str(value).strip() for value in raw_row):
            continue
        row = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            row[header] = raw_row[index] if index < len(raw_row) else ""
        rows.append(row)
    return rows


def _restore_runtime_state_from_sheets(rows_by_sheet):
    """Restore only durable admin configuration from the clean BotConfig tab."""
    global bot_settings

    config_rows = rows_by_sheet.get("BotConfig", []) or []
    if config_rows:
        try:
            # Read the current two-column format.  Also accept the previous
            # one-row state_json format so an existing sheet migrates cleanly
            # on its next successful sync.
            stored_settings = {}
            if config_rows[0].get("state_json"):
                stored_config = json.loads(config_rows[0].get("state_json", "{}"))
                stored_settings = stored_config.get("bot_settings")
            else:
                for row in config_rows:
                    setting = str(row.get("setting") or row.get("key") or "").strip()
                    if not setting:
                        continue
                    raw_value = row.get("value_json", row.get("value", ""))
                    try:
                        stored_settings[setting] = json.loads(raw_value)
                    except (TypeError, ValueError):
                        stored_settings[setting] = raw_value
            if isinstance(stored_settings, dict):
                # Stored settings are authoritative. Only keys introduced by a
                # newer code version are filled from the current defaults.
                current_defaults = copy.deepcopy(bot_settings)
                bot_settings = _fill_missing_settings(
                    current_defaults, stored_settings
                )
                ensure_premium_apps()
                bot_settings["admins"] = list(dict.fromkeys(
                    [
                        int(item) if str(item).lstrip("-").isdigit() else item
                        for item in bot_settings.get("admins", [])
                    ] + ALL_ADMIN_IDS
                ))
                bot_settings = _deduplicate_bot_settings(bot_settings)
        except Exception as exc:
            print(f"⚠️ Stored bot configuration could not be restored: {exc}")


def _fill_missing_settings(defaults, stored):
    """Apply stored settings while retaining only missing newer defaults."""
    result = copy.deepcopy(defaults) if isinstance(defaults, dict) else {}
    if not isinstance(stored, dict):
        return result
    for key, value in stored.items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _fill_missing_settings(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _deduplicate_bot_settings(settings):
    """Remove repeated admin settings before runtime use or Sheets export."""
    if not isinstance(settings, dict):
        return {}
    result = copy.deepcopy(settings)

    def unique_values(values):
        output = []
        seen = set()
        for value in values if isinstance(values, list) else []:
            marker = json.dumps(
                value, ensure_ascii=False, sort_keys=True, default=str
            )
            if marker not in seen:
                seen.add(marker)
                output.append(value)
        return output

    for key in (
        "admins", "fj_channels", "stex_keys", "voltx_keys", "zenex_keys",
        "search_countries", "voltx_search_countries",
        "zenex_search_countries", "w_methods",
    ):
        if key in result:
            result[key] = unique_values(result.get(key))

    panels = []
    panel_markers = set()
    for panel in (
        result.get("panels", [])
        if isinstance(result.get("panels"), list) else []
    ):
        if not isinstance(panel, dict):
            continue
        marker = json.dumps(
            panel, ensure_ascii=False, sort_keys=True, default=str
        )
        if marker not in panel_markers:
            panel_markers.add(marker)
            panels.append(panel)
    result["panels"] = panels

    for service_key in ("stex_services", "voltx_services", "zenex_services"):
        services = result.get(service_key)
        if not isinstance(services, dict):
            continue
        for countries in services.values():
            if not isinstance(countries, dict):
                continue
            for country, ranges in list(countries.items()):
                countries[country] = unique_values(ranges)

    custom_messages = result.get("custom_messages")
    if isinstance(custom_messages, dict):
        for message in custom_messages.values():
            if isinstance(message, dict) and isinstance(message.get("buttons"), list):
                message["buttons"] = unique_values(message["buttons"])
    return result


def _as_number(value, default=0):
    try:
        number = float(str(value).strip())
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return default


def _normalize_username(value):
    """Store Telegram usernames consistently as @username or an empty string."""
    value = str(value or "").strip()
    if not value:
        return ""
    return "@" + value.lstrip("@")


def _is_group_or_channel_record(row):
    """Reject group/channel records from user and financial Sheets tabs."""
    if not isinstance(row, dict):
        return True
    for field in ("user_id", "id", "chat_id", "group_id", "channel_id", "sender_chat_id"):
        value = row.get(field)
        if value is None or str(value).strip() == "":
            continue
        text = str(value).strip()
        if re.fullmatch(r"-\d+", text):
            return True
    chat_type = str(row.get("chat_type", row.get("type", "")) or "").lower()
    return chat_type in {"group", "supergroup", "channel"}


def _merge_record_values(existing, incoming):
    """Merge a record while keeping meaningful values from both copies."""
    result = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return result
    for key, value in incoming.items():
        # A blank value from an old CSV/XLSX export must not erase a real value
        # already present. False and numeric zero are meaningful and do update.
        if key not in result or value not in (None, ""):
            result[key] = copy.deepcopy(value)
    return result


def _deduplicate_collection_rows(value, collection_name):
    """Return one canonical record per user/request/event identity.

    Google Sheets is row based while the runtime store is document based. A
    restore can therefore contain duplicate rows with different generated
    document IDs. This function collapses those rows before they reach runtime
    and before the next Sheets rewrite.
    """
    if isinstance(value, dict):
        source = value.items()
    elif isinstance(value, list):
        source = enumerate(value)
    else:
        source = []

    result = {}
    for source_key, raw_row in source:
        if not isinstance(raw_row, dict):
            continue
        row = copy.deepcopy(raw_row)
        if collection_name == "users":
            if _is_group_or_channel_record(row):
                continue
            identity = str(
                row.get("user_id") or row.get("id") or source_key or ""
            ).strip()
            if not identity or not re.fullmatch(r"\d+", identity) or identity == "0":
                continue
            row["user_id"] = identity
        elif collection_name == "withdrawals":
            if _is_group_or_channel_record(row):
                continue
            identity = str(row.get("request_id") or "").strip()
            if not identity:
                identity = "RESTORED_" + hashlib.sha256(
                    _stable_json_key({
                        "user_id": row.get("user_id", ""),
                        "amount": row.get("amount", ""),
                        "method": row.get("method", ""),
                        "number": row.get("number", ""),
                        "timestamp": row.get("timestamp", ""),
                    }).encode("utf-8")
                ).hexdigest()[:20]
            row["request_id"] = identity
        else:
            if _is_group_or_channel_record(row):
                continue
            identity = str(row.get("event_id") or "").strip()
            if not identity:
                identity = "RESTORED_" + hashlib.sha256(
                    _stable_json_key({
                        "user_id": row.get("user_id", ""),
                        "event_type": row.get("event_type", ""),
                        "amount": row.get("amount", ""),
                        "status": row.get("status", ""),
                        "method": row.get("method", ""),
                        "request_id": row.get("request_id", ""),
                        "timestamp": row.get("timestamp", ""),
                        "message": row.get("message", ""),
                    }).encode("utf-8")
                ).hexdigest()[:20]
            row["event_id"] = identity

        if identity in result:
            result[identity] = _merge_record_values(result[identity], row)
        else:
            result[identity] = row
    return result


def _restore_rows_to_runtime(rows_by_sheet):
    """Replace only Google-backed collections with imported sheet rows."""
    users = list(_deduplicate_collection_rows(
        rows_by_sheet.get("Users", []) or [], "users"
    ).values())
    withdrawals = list(_deduplicate_collection_rows(
        rows_by_sheet.get("Withdrawals", []) or [], "withdrawals"
    ).values())
    history = list(_deduplicate_collection_rows(
        rows_by_sheet.get("History", []) or [], "history"
    ).values())

    for collection_name in ("users", "withdrawals", "history"):
        with _runtime_store_lock:
            _runtime_collections[collection_name] = {}

    for row in users:
        uid = str(row.get("user_id") or row.get("id") or "").strip()
        if not uid:
            continue
        user = dict(row)
        user["user_id"] = _as_number(uid, uid)
        old_username_value = str(row.get("username", "") or "").strip()
        user["user_name"] = str(
            row.get("user_name")
            or row.get("full_name")
            or (
                old_username_value
                if old_username_value and not old_username_value.startswith("@")
                and " " in old_username_value
                else ""
            )
            or ""
        )[:120]
        username_candidate = (
            old_username_value
            if old_username_value and (
                old_username_value.startswith("@") or " " not in old_username_value
            )
            else ""
        )
        user["username"] = _normalize_username(username_candidate)[:120]
        user["balance"] = _as_number(row.get("balance"), 0.0)
        user["total_refers"] = _as_number(row.get("total_refers"), 0)
        user["total_otps"] = _as_number(row.get("total_otps"), 0)
        user["otp"] = str(row.get("otp", "") or "")
        user["banned"] = str(row.get("banned", "")).lower() in ("1", "true", "yes")
        user["verified"] = str(row.get("verified", "")).lower() in ("1", "true", "yes")
        db.collection("users").document(uid).set(user)

    for index, row in enumerate(withdrawals):
        request_id = str(row.get("request_id") or f"RESTORED_{index + 1}")
        item = dict(row)
        item["request_id"] = request_id
        item["user_id"] = str(row.get("user_id", ""))
        item["amount"] = _as_number(row.get("amount"), 0.0)
        item["status"] = str(row.get("status", "pending") or "pending").lower()
        db.collection("withdrawals").document(request_id).set(item)

    for index, row in enumerate(history):
        event_id = str(row.get("event_id") or f"RESTORED_{index + 1}")
        item = dict(row)
        item["event_id"] = event_id
        item["amount"] = _as_number(row.get("amount"), row.get("amount", ""))
        db.collection("history").document(event_id).set(item)

    local_users.clear()
    for snapshot in db.collection("users").stream():
        local_users[snapshot.id] = snapshot.to_dict()
    audit_history.clear()
    audit_history.extend(
        snapshot.to_dict() for snapshot in db.collection("history").stream()
    )
    all_known_users.clear()
    all_known_users.update(local_users.keys())
    user_cache.clear()
    pending_withdrawals.clear()
    for snapshot in db.collection("withdrawals").stream():
        item = snapshot.to_dict()
        if str(item.get("status", "pending")).lower() == "pending":
            pending_withdrawals[snapshot.id] = item


def load_google_sheet_data():
    """Load persistent user/withdrawal/history rows before handlers start."""
    global google_sheet_data_loaded, google_sheet_load_error
    global google_sheet_last_signature
    if not google_sheets_configured():
        google_sheet_load_error = "Google Sheets is not configured."
        return False
    try:
        token = _google_access_token()
        if not token:
            return False
        _ensure_google_sheet_tabs(token)
        rows_by_sheet = {
            name: _sheet_rows(token, name)
            for name in GOOGLE_SHEET_NAMES
        }
        _restore_runtime_state_from_sheets(rows_by_sheet)
        _restore_rows_to_runtime(rows_by_sheet)
        google_sheet_data_loaded = True
        google_sheet_load_error = ""
        # Rewrite the sheet immediately from the canonical runtime records.
        # This removes duplicates that were already present before this build.
        google_sheet_last_signature = None
        cleaned_sheet = sync_to_google_sheets(force=True)
        print(
            "✅ Loaded persistent users, withdrawals and history from Google Sheets."
        )
        if cleaned_sheet:
            notify_google_restore_success()
        return True
    except Exception as exc:
        google_sheet_load_error = str(exc)
        print(f"⚠️ Google Sheets initial load failed: {exc}")
        return False


def _rows_to_matrix(rows, sheet_name=None):
    headers = list(GOOGLE_SHEET_HEADERS.get(sheet_name, []))
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    if not headers:
        return [[]]
    return [headers] + [[_json_cell(row.get(key, "")) for key in headers] for row in rows]


def sync_to_google_sheets(force=False):
    global google_sheet_last_signature, google_sheet_last_error, google_sheet_initial_sync
    if not google_sheets_configured():
        return False
    # Never clear a sheet because a temporary startup/auth failure produced an
    # empty in-memory store.  An explicit restore or a successful initial load
    # must happen first.
    if not google_sheet_data_loaded:
        return False
    try:
        rows_by_sheet = _google_sheet_rows()
        signature = hashlib.sha256(
            json.dumps(rows_by_sheet, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if not force and signature == google_sheet_last_signature:
            return True
        token = _google_access_token()
        if not token:
            return False
        _ensure_google_sheet_tabs(token)
        base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}"
        ranges = [f"{name}!A:ZZ" for name in GOOGLE_SHEET_NAMES]
        _google_api("POST", f"{base_url}/values:batchClear", token, {"ranges": ranges})
        _google_api(
            "POST",
            f"{base_url}/values:batchUpdate",
            token,
            {
                "valueInputOption": "RAW",
                "data": [
                    {
                        "range": f"{name}!A1",
                        "values": _rows_to_matrix(rows_by_sheet[name], name),
                    }
                    for name in GOOGLE_SHEET_NAMES
                ],
            },
        )
        google_sheet_last_signature = signature
        google_sheet_last_error = ""
        if google_sheet_initial_sync:
            print("✅ Google Sheets sync is active (1 second check interval).")
            google_sheet_initial_sync = False
        return True
    except Exception as exc:
        google_sheet_last_error = str(exc)
        if google_sheet_initial_sync:
            print(f"⚠️ Google Sheets sync is not ready: {exc}")
            google_sheet_initial_sync = False
        return False


def trigger_google_sheets_sync():
    """Debounce immediate syncs so one update cannot create duplicate writes."""
    global google_sync_trigger_scheduled
    if not google_sheets_configured():
        return
    with google_sync_trigger_lock:
        if google_sync_trigger_scheduled:
            return
        google_sync_trigger_scheduled = True

    def _run():
        global google_sync_trigger_scheduled
        try:
            # Coalesce several balance/OTP/referral changes into one sheet write.
            time.sleep(0.5)
            with google_sync_lock:
                sync_to_google_sheets()
        except Exception as exc:
            print(f"⚠️ Immediate Google Sheets sync failed: {exc}")
        finally:
            with google_sync_trigger_lock:
                google_sync_trigger_scheduled = False

    threading.Thread(target=_run, daemon=True).start()


def google_sheets_sync_thread():
    while True:
        try:
            # A transient startup/auth/network failure must not leave the bot
            # permanently empty.  Retry the read first; only a successful
            # read unlocks writes, so a blank runtime can never overwrite the
            # real Google Sheet data.
            if not google_sheet_data_loaded:
                with google_sync_lock:
                    load_google_sheet_data()
            else:
                with google_sync_lock:
                    synced = sync_to_google_sheets()
                    if synced:
                        notify_google_restore_success()
        except Exception:
            pass
        time.sleep(GOOGLE_SYNC_INTERVAL)


def get_google_sheet_status_text():
    if not google_sheets_configured():
        return (
            "📊 <b>GOOGLE SHEETS SYNC</b>\n\n"
            "Status: <b>NOT CONFIGURED</b>\n\n"
            "Set these environment variables and restart the bot:\n"
            "<code>GOOGLE_SHEET_ID</code>\n"
            "<code>GOOGLE_SERVICE_ACCOUNT_JSON</code>\n\n"
            "Share the Google Sheet with the service-account email as Editor."
        )
    status_error = google_sheet_last_error or google_sheet_load_error
    status = "READY" if not status_error and google_sheet_data_loaded else "ERROR"
    detail = (
        f"\n\nLast error: <code>{html.escape(status_error[:300])}</code>"
        if status_error else ""
    )
    return (
        "📊 <b>GOOGLE SHEETS SYNC</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Mode: Google Sheets only; checked every {GOOGLE_SYNC_INTERVAL:g} seconds\n"
        "Tabs: Users, Withdrawals, History, BotConfig\n"
        "Runtime-only number claims and OTP caches are never written to Sheets."
        f"{detail}"
    )


def record_history(user_id, event_type, message="", amount=None, status=None,
                   method=None, request_id=None, balance_after=None,
                   payment_number=None):
    """Store only useful financial/user events; never store OTP text or service numbers."""
    entry = {
        "event_id": uuid.uuid4().hex[:18],
        "user_id": str(user_id),
        "event_type": str(event_type),
        "message": str(message or "")[:500],
        "amount": amount,
        "status": status,
        "method": method,
        "request_id": request_id,
        "balance_after": balance_after,
        "timestamp": iso_now(),
        "data_month": data_month_key()
    }
    if payment_number is not None:
        entry["payment_number"] = str(payment_number)[:80]

    try:
        if db:
            db.collection("history").document(entry["event_id"]).set(entry)
            trigger_google_sheets_sync()
        else:
            audit_history.append(entry)
            if len(audit_history) > 10000:
                del audit_history[:-10000]
            save_user_store()
    except Exception:
        pass
    return entry


def _delete_collection_documents(collection_name):
    if not db:
        return
    try:
        for snapshot in db.collection(collection_name).stream():
            db.collection(collection_name).document(snapshot.id).delete()
    except Exception as exc:
        print(f"⚠️ Could not clear {collection_name}: {exc}")


def ensure_monthly_data_reset():
    """Reset monthly user/financial history on the first Dhaka-calendar day."""
    global data_month, audit_history, user_cache
    current_month = data_month_key()
    if data_month == current_month:
        return False

    print(f"🧹 Monthly reset: {data_month} -> {current_month}")

    if db:
        try:
            for snapshot in db.collection("users").stream():
                user_doc = snapshot.to_dict()
                db.collection("users").document(snapshot.id).update({
                    "balance": 0.0,
                    "total_otps": 0,
                    "total_refers": 0,
                    "monthly_reset_at": iso_now()
                })
        except Exception as exc:
            print(f"⚠️ Could not reset user balances: {exc}")
        _delete_collection_documents("history")
        _delete_collection_documents("withdrawals")
    else:
        for uid, user in local_users.items():
            user["balance"] = 0.0
            user["total_otps"] = 0
            user["total_refers"] = 0
            user["monthly_reset_at"] = iso_now()
        audit_history = []

    # Runtime number-usage data is disposable and is not persisted anymore.
    used_numbers_list.clear()
    with number_allocation_lock:
        claimed_numbers.clear()
    stex_assigned_numbers.clear()
    voltx_assigned_numbers.clear()
    zenex_assigned_numbers.clear()
    processed_otps.clear()
    assigned_number_rates.clear()
    recent_traffic.clear()
    if "user_cache" in globals():
        user_cache.clear()
    data_month = current_month
    save_db()
    return True


load_db()
ensure_monthly_data_reset()
# Rewrite the state once on startup so legacy used-number/OTP caches are
# removed from older local state files as well.
save_db()

user_states = {}
temp_data = {}
user_cooldowns = {}
pending_withdrawals = {}

# ==========================================
# Telegram API & Helpers
# ==========================================
tg_session = requests.Session()

def api_call(method, payload=None):
    url = f"{BASE_URL}/{method}"
    try:
        res = tg_session.post(url, json=payload, timeout=15)
        return res.json()
    except Exception as e:
        return {}

UI_TRANSLATIONS_BN = {
    "SELECT LANGUAGE": "ভাষা নির্বাচন করুন",
    "CHOOSE YOUR LANGUAGE": "আপনার ভাষা নির্বাচন করুন",
    "NAVIGATION MENU": "নেভিগেশন মেনু",
    "ENGLISH": "ইংরেজি",
    "BANGLA": "বাংলা",
    "GET NUMBER": "নম্বর নিন",
    "TRAFFIC": "ট্রাফিক",
    "2FA ONLINE": "২এফএ অনলাইন",
    "REFER": "রেফার",
    "WITHDRAWAL": "উত্তোলন",
    "SUPPORT": "সাপোর্ট",
    "CHANGE LANGUAGE": "ভাষা পরিবর্তন করুন",
    "RESTART BOT": "বট রিস্টার্ট করুন",
    "ADMIN PANEL": "অ্যাডমিন প্যানেল",
    "CLOSE": "বন্ধ করুন",
    "CANCEL": "বাতিল",
    "REFRESH": "রিফ্রেশ",
    "COPY LINK": "লিংক কপি করুন",
    "CONTACT SUPPORT": "সাপোর্টে যোগাযোগ করুন",
    "GENERATE 2FA CODE": "২এফএ কোড তৈরি করুন",
    "EXPLORE": "এক্সপ্লোর",
    "RANGE": "রেঞ্জ",
    "SELECT A SERVICE": "একটি সার্ভিস নির্বাচন করুন",
    "SELECT A COUNTRY": "একটি দেশ নির্বাচন করুন",
    "NO NUMBERS OR SERVICES AVAILABLE!": "কোনো নম্বর বা সার্ভিস পাওয়া যায়নি!",
    "NO RECENT TRAFFIC FOUND IN THE LAST 10 MINUTES...": "গত ১০ মিনিটে কোনো ট্রাফিক পাওয়া যায়নি...",
    "UPDATED": "আপডেট হয়েছে",
    "ENTER 3 TO 9 DIGITS": "৩ থেকে ৯ ডিজিট লিখুন",
    "FAST NUMBER LOOKUP SYSTEM": "দ্রুত নম্বর খোঁজার সিস্টেম",
    "CONTACT US FOR ANY HELP:": "যেকোনো সাহায্যের জন্য যোগাযোগ করুন:",
    "SELECT METHOD:": "মেথড নির্বাচন করুন:",
    "YOUR LINK:": "আপনার লিংক:",
    "TOTAL REFERS:": "মোট রেফার:",
    "PER REFER:": "প্রতি রেফারে:",
    "NUMBER BOT": "নম্বর বট",
    "WELCOME TO NUMBER & OTP SERVICE": "নম্বর ও ওটিপি সার্ভিসে স্বাগতম",
    "CHOOSE AN OPTION BELOW": "নিচের অপশনটি নির্বাচন করুন",
    "TO CONTINUE USING THE BOT": "বট ব্যবহার চালিয়ে যেতে",
    "PREMIUM OTP SERVICE": "প্রিমিয়াম ওটিপি সার্ভিস",
    "TRAFFIC OVERVIEW": "ট্রাফিকের বিবরণ",
    "AVAILABLE NUMBERS": "উপলভ্য নম্বর",
    "ASSIGNED NUMBERS": "বরাদ্দ করা নম্বর",
    "10 MINUTE LIVE TRAFFIC": "১০ মিনিটের লাইভ ট্রাফিক",
    "LOW": "কম",
    "MEDIUM": "মাঝারি",
    "HIGH": "বেশি",
    "SELECT A SERVICE:": "একটি সার্ভিস নির্বাচন করুন:",
    "SELECT A COUNTRY": "একটি দেশ নির্বাচন করুন",
    "ENTER 3 TO 9 DIGITS": "৩ থেকে ৯ ডিজিট লিখুন",
    "EXAMPLE:": "উদাহরণ:",
    "TOTAL OTP": "মোট ওটিপি",
    "BALANCE:": "ব্যালেন্স:",
    "MINIMUM:": "সর্বনিম্ন:",
    "WITHDRAWAL": "উত্তোলন",
    "REFER & EARN": "রেফার করুন ও আয় করুন",
    "TOTAL REFERS": "মোট রেফার",
    "PER REFER": "প্রতি রেফারে",
    "NO NUMBERS OR SERVICES AVAILABLE!": "কোনো নম্বর বা সার্ভিস পাওয়া যায়নি!",
    "NO RECENT TRAFFIC FOUND": "সাম্প্রতিক কোনো ট্রাফিক পাওয়া যায়নি",
    "UPDATED": "আপডেট হয়েছে",
    "JOIN CHANNEL": "চ্যানেলে যোগ দিন",
    "CHECK JOINED": "যোগ দেওয়া যাচাই করুন",
}

def get_user_language(user_id):
    """Return the selected UI language; legacy users fall back to English."""
    # Negative Telegram IDs are groups/channels, not user profiles.
    if isinstance(user_id, int) and user_id < 0:
        return "EN"
    try:
        return get_user(user_id).get("language") or "EN"
    except Exception:
        return "EN"

def localize_ui_text(chat_id, text):
    if not text or get_user_language(chat_id) != "BN":
        return text
    result = str(text)
    for source, target in sorted(UI_TRANSLATIONS_BN.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(re.escape(source), target, result, flags=re.IGNORECASE)
    return result

def localize_markup(chat_id, reply_markup):
    if not reply_markup or get_user_language(chat_id) != "BN":
        return reply_markup
    markup = copy.deepcopy(reply_markup)
    for keyboard_key in ("keyboard", "inline_keyboard"):
        for row in markup.get(keyboard_key, []) if isinstance(markup, dict) else []:
            for button in row:
                if isinstance(button, dict) and "text" in button:
                    button["text"] = localize_ui_text(chat_id, button["text"])
    return markup

_BOLD_BUTTON_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)
_NORMAL_BUTTON_TRANSLATION = str.maketrans(
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
)
_LEGACY_NORMAL_BUTTON_TRANSLATION = str.maketrans(
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
)

def bold_button_text(text):
    """Use Unicode bold glyphs because Telegram does not parse HTML in buttons."""
    # Keep the original casing (e.g. Facebook) while making the label bold.
    return str(text).translate(_BOLD_BUTTON_TRANSLATION)

def normal_button_text(text):
    """Convert a bold reply-keyboard label back before command matching."""
    return str(text).translate(_NORMAL_BUTTON_TRANSLATION).translate(_LEGACY_NORMAL_BUTTON_TRANSLATION)

def _service_name_pattern():
    names = {
        str(value.get("name", key)).strip()
        for key, value in bot_settings.get("premium_apps", {}).items()
        if str(value.get("name", key)).strip()
    }
    names.update(str(key).replace("_", " ").strip() for key in bot_settings.get("premium_apps", {}))
    # Include detected SMS services, admin-added stock services, and every
    # configured withdrawal method. This keeps names such as Facebook, a
    # custom service, bKash, or Nagad bold in both messages and buttons.
    names.update(
        str(key).replace("_", " ").strip()
        for key in globals().get("SERVICE_SMS_KEYWORDS", {})
    )
    names.update(
        str(method).strip()
        for method in bot_settings.get("w_methods", [])
        if str(method).strip()
    )
    for batch in number_batches.values():
        if isinstance(batch, dict) and str(batch.get("service", "")).strip():
            names.add(str(batch["service"]).strip())
    for setting_key in ("stex_services", "voltx_services", "zenex_services"):
        names.update(
            str(service).replace("_", " ").strip()
            for service in bot_settings.get(setting_key, {})
            if str(service).strip()
        )
    names = sorted((name for name in names if name), key=len, reverse=True)
    if not names:
        return None
    return re.compile(
        r"(?<![\w])(" + "|".join(re.escape(name) for name in names) + r")(?![\w])",
        flags=re.IGNORECASE,
    )

def bold_service_names(text):
    """Bold only known service names, leaving the surrounding text normal."""
    pattern = _service_name_pattern()
    if not pattern:
        return str(text)
    return pattern.sub(lambda match: bold_button_text(match.group(1)), str(text))

def normalize_body_formatting(text):
    """Keep body copy normal, except for the service names requested by the user."""
    if not text:
        return text
    normal_text = str(text).translate(_NORMAL_BUTTON_TRANSLATION).translate(_LEGACY_NORMAL_BUTTON_TRANSLATION)
    normal_text = re.sub(r"</?(?:b|strong|i|em)>", "", normal_text, flags=re.IGNORECASE)
    return bold_service_names(normal_text)

def bold_button_markup(reply_markup, chat_id=None):
    """Bold reply-keyboard labels and only known app names in inline buttons."""
    if not reply_markup:
        return reply_markup
    markup = localize_markup(chat_id, reply_markup) if chat_id is not None else copy.deepcopy(reply_markup)
    for keyboard_key in ("keyboard", "inline_keyboard"):
        for row in markup.get(keyboard_key, []) if isinstance(markup, dict) else []:
            for button in row:
                if isinstance(button, dict) and "text" in button:
                    if keyboard_key == "keyboard":
                        button["text"] = bold_button_text(button["text"])
                    else:
                        button["text"] = bold_service_names(button["text"])
    return markup

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    body_text = normalize_body_formatting(localize_ui_text(chat_id, text))
    payload = {"chat_id": chat_id, "text": body_text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = bold_button_markup(reply_markup, chat_id)
    return api_call("sendMessage", payload)


def get_configured_admin_ids():
    """Return owner, environment admins, and admins restored from bot settings."""
    values = list(ALL_ADMIN_IDS)
    for value in bot_settings.get("admins", []) if isinstance(bot_settings, dict) else []:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(values))


def notify_google_restore_success():
    """Notify admins once after the first successful startup/online restore."""
    global google_startup_notice_sent
    if google_startup_notice_sent or not google_sheet_data_loaded:
        return False
    with google_startup_notice_lock:
        if google_startup_notice_sent:
            return True
        message = (
            f"{PEM['ok']} <b>Google Sheets data auto-restored successfully.</b>\n\n"
            "All Users, Withdrawals and History data were loaded when the bot "
            "came online. Duplicate records were merged and the cleaned data "
            "was synced back to Google Sheets."
        )
        sent = False
        for admin_id in get_configured_admin_ids():
            result = send_message(admin_id, render_body_text(message))
            if result and result.get("ok"):
                sent = True
        if sent:
            google_startup_notice_sent = True
        return sent


def send_photo(chat_id, photo_url_or_file_id, caption="", reply_markup=None, parse_mode="HTML"):
    body_caption = normalize_body_formatting(localize_ui_text(chat_id, caption))
    payload = {"chat_id": chat_id, "photo": photo_url_or_file_id, "caption": body_caption, "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = bold_button_markup(reply_markup, chat_id)
    return api_call("sendPhoto", payload)

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    body_text = normalize_body_formatting(localize_ui_text(chat_id, text))
    payload = {"chat_id": chat_id, "message_id": message_id, "text": body_text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = bold_button_markup(reply_markup, chat_id)
    return api_call("editMessageText", payload)

def delete_message(chat_id, message_id):
    return api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def answer_callback(callback_id, text="", show_alert=False):
    api_call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": show_alert})

def send_document(chat_id, filename, text_content):
    url = f"{BASE_URL}/sendDocument"
    files = {'document': (filename, text_content)}
    data = {'chat_id': chat_id}
    try:
        response = requests.post(url, data=data, files=files, timeout=60)
        if response.content:
            return response.json()
        return {"ok": response.ok, "description": response.text[:300]}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


PERSISTENT_COLLECTIONS = ("users", "history", "withdrawals")


def _export_database_collections():
    """Export the Google-backed runtime collections used by the admin backup."""
    if not db:
        raise RuntimeError("Runtime storage is unavailable.")
    if google_sheets_configured() and not google_sheet_data_loaded:
        raise RuntimeError(
            "Google Sheets data has not loaded yet; backup was stopped to avoid "
            "sending a false empty file."
        )
    result = {}
    for collection_name in PERSISTENT_COLLECTIONS:
        result[collection_name] = {
            snapshot.id: snapshot.to_dict()
            for snapshot in db.collection(collection_name).stream()
        }
    return result


def _clear_database_collection(collection_name):
    if not db:
        raise RuntimeError("Runtime storage is unavailable.")
    for snapshot in db.collection(collection_name).stream():
        db.collection(collection_name).document(snapshot.id).delete()


def _replace_database_collections(collections):
    if not isinstance(collections, dict):
        raise ValueError("Backup collections are invalid.")
    for collection_name in PERSISTENT_COLLECTIONS:
        _clear_database_collection(collection_name)
        rows = collections.get(collection_name, {})
        if not isinstance(rows, dict):
            continue
        for document_id, value in rows.items():
            if isinstance(value, dict):
                db.collection(collection_name).document(str(document_id)).set(value)


def build_full_backup():
    """Return a JSON backup of the real bot state.

    The bot deliberately does not export environment secrets such as BOT_TOKEN
    or Google service-account credentials.  API/provider keys that are part of
    the admin-managed bot configuration are included because they are bot data
    and are required for a true restore.

    Telegram UI state and live HTTP sessions are intentionally omitted: message
    IDs, cooldowns and open provider sessions are temporary and cannot be
    restored safely after a restart.
    """
    collections = _export_database_collections()
    runtime_state = {
        "bot_settings": copy.deepcopy(bot_settings),
        "number_batches": copy.deepcopy(number_batches),
        "used_numbers_list": copy.deepcopy(used_numbers_list),
        "stex_assigned_numbers": copy.deepcopy(stex_assigned_numbers),
        "voltx_assigned_numbers": copy.deepcopy(voltx_assigned_numbers),
        "zenex_assigned_numbers": copy.deepcopy(zenex_assigned_numbers),
        "assigned_number_rates": copy.deepcopy(assigned_number_rates),
        "total_uploaded_stats": total_uploaded_stats,
        "total_assigned_stats": total_assigned_stats,
        "processed_otps": sorted(str(item) for item in processed_otps),
        "recent_traffic": copy.deepcopy(recent_traffic),
    }
    return {
        "backup_format": "gx-number-bot-full-state",
        "backup_version": 4,
        "created_at": iso_now(),
        "data_month": data_month,
        "persistent_source": "Google Sheets plus runtime state",
        "included_tabs": list(GOOGLE_SHEET_NAMES),
        # Everything configurable from the admin panel is kept together in
        # this section, including provider API keys/panel credentials that are
        # stored in bot_settings.
        "admin_panel": {
            "settings": copy.deepcopy(bot_settings),
            "runtime": copy.deepcopy(runtime_state),
        },
        # This is the exact Google-backed data currently held by the bot and
        # mirrored by the automatic Sheets sync. It is included as one JSON
        # snapshot so the same restore file can rebuild the sheet-backed data.
        "google_sheets": {
            "tabs": {
                "Users": list(collections.get("users", {}).values()),
                "Withdrawals": list(collections.get("withdrawals", {}).values()),
                "History": list(collections.get("history", {}).values()),
            },
            "sync_enabled": google_sheets_configured(),
            "sync_loaded": google_sheet_data_loaded,
        },
        "collections": collections,
        "runtime": runtime_state,
    }


def _stable_json_key(value):
    """Create a deterministic key for de-duplicating JSON-compatible values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _unique_values(existing, incoming):
    """Append new list values without changing the existing order."""
    result = []
    seen = set()
    for value in list(existing or []) + list(incoming or []):
        key = _stable_json_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(copy.deepcopy(value))
    return result


def _merge_settings(existing, incoming):
    """Merge imported settings without deleting settings already in the bot."""
    if not isinstance(existing, dict):
        existing = {}
    if not isinstance(incoming, dict):
        return copy.deepcopy(existing)
    result = copy.deepcopy(existing)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_settings(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = _unique_values(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _merge_number_batches(existing, incoming):
    """Merge number files and de-duplicate numbers inside each matching file."""
    result = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return result
    for batch_id, imported_batch in incoming.items():
        batch_key = str(batch_id)
        if not isinstance(imported_batch, dict):
            continue
        current_batch = result.get(batch_key)
        if not isinstance(current_batch, dict):
            current_batch = {}
        merged_batch = _merge_settings(current_batch, imported_batch)
        old_numbers = current_batch.get("numbers", [])
        new_numbers = imported_batch.get("numbers", [])
        if isinstance(old_numbers, list) and isinstance(new_numbers, list):
            # Numbers are unique by their actual "num" value, not by the
            # complete object, because used_by/rate metadata can differ.
            merged_numbers = []
            number_indexes = {}
            for item in old_numbers + new_numbers:
                if not isinstance(item, dict):
                    key = _stable_json_key(item)
                    if key not in number_indexes:
                        number_indexes[key] = len(merged_numbers)
                        merged_numbers.append(copy.deepcopy(item))
                    continue
                number_key = str(item.get("num", "")).strip()
                key = f"num:{number_key}" if number_key else _stable_json_key(item)
                if key not in number_indexes:
                    number_indexes[key] = len(merged_numbers)
                    merged_numbers.append(copy.deepcopy(item))
                    continue
                index = number_indexes[key]
                old_item = merged_numbers[index]
                if isinstance(old_item, dict):
                    merged_numbers[index] = _merge_settings(old_item, item)
                    if isinstance(old_item.get("used_by"), list) and isinstance(
                        item.get("used_by"), list
                    ):
                        merged_numbers[index]["used_by"] = _unique_values(
                            old_item["used_by"], item["used_by"]
                        )
            merged_batch["numbers"] = merged_numbers
        result[batch_key] = merged_batch
    return result


def _deduplicate_number_batches(batches):
    """Keep one copy of a number even when it appears in different files."""
    if not isinstance(batches, dict):
        return {}
    result = copy.deepcopy(batches)
    seen_numbers = set()
    for batch in result.values():
        if not isinstance(batch, dict) or not isinstance(batch.get("numbers"), list):
            continue
        unique_numbers = []
        for item in batch["numbers"]:
            if isinstance(item, dict):
                number_key = str(item.get("num", "")).strip()
                if number_key:
                    if number_key in seen_numbers:
                        continue
                    seen_numbers.add(number_key)
            unique_numbers.append(item)
        batch["numbers"] = unique_numbers
    return result


def _merge_collection_maps(current, imported):
    """Merge records by document ID; imported values win on the same ID."""
    result = copy.deepcopy(current) if isinstance(current, dict) else {}
    if not isinstance(imported, dict):
        return result
    for document_id, value in imported.items():
        key = str(document_id)
        if not isinstance(value, dict):
            continue
        if isinstance(result.get(key), dict):
            result[key] = _merge_record_values(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def send_full_backup(chat_id):
    try:
        payload = json.dumps(
            build_full_backup(), ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
    except Exception as exc:
        send_message(
            chat_id,
            render_body_text(
                f"❌ <b>Backup stopped:</b> <code>{html.escape(str(exc))}</code>"
            ),
        )
        return False
    result = send_document(
        chat_id, f"bot_full_backup_{data_month_key()}.json", payload
    )
    if not result or not result.get("ok"):
        description = html.escape(
            str((result or {}).get("description", "Telegram upload failed"))
        )
        send_message(
            chat_id,
            render_body_text(
                f"❌ <b>Backup upload failed:</b> <code>{description}</code>"
            ),
        )
        return False
    send_message(
        chat_id,
        render_body_text(
            f"{PEM['ok']} <b>Full backup created and sent.</b>\n"
            "The JSON contains the complete Admin Panel state plus the "
            "Google Sheets Users, Withdrawals and History snapshot, including "
            "number stock, provider configuration and runtime counters. "
            "Telegram tokens and Google service-account credentials are never "
            "exported."
        ),
    )
    return True


def restore_full_backup(backup):
    """Merge a validated JSON/full-state or sheet import into bot data."""
    global data_month, google_sheet_data_loaded, google_sheet_load_error
    global bot_settings, number_batches, used_numbers_list
    global stex_assigned_numbers, voltx_assigned_numbers
    global zenex_assigned_numbers, assigned_number_rates
    global total_uploaded_stats, total_assigned_stats
    global processed_otps, recent_traffic
    if not isinstance(backup, dict):
        raise ValueError("Backup must contain imported sheet data.")
    collections = copy.deepcopy(backup.get("collections", {}))
    if not isinstance(collections, dict):
        raise ValueError("Backup collections are invalid.")
    # Older/manual JSON backups can carry user/history arrays instead.
    for name in ("users", "history", "withdrawals"):
        if name not in collections and name in backup:
            collections[name] = backup[name]

    collections["users"] = _deduplicate_collection_rows(
        collections.get("users", {}), "users"
    )
    collections["history"] = _deduplicate_collection_rows(
        collections.get("history", {}), "history"
    )
    collections["withdrawals"] = _deduplicate_collection_rows(
        collections.get("withdrawals", {}), "withdrawals"
    )

    # A restore is additive. Existing records remain, while a matching
    # document ID is treated as the same record and updated from the file.
    current_collections = {
        collection_name: _deduplicate_collection_rows(
            {
                snapshot.id: snapshot.to_dict()
                for snapshot in db.collection(collection_name).stream()
            },
            collection_name,
        )
        for collection_name in PERSISTENT_COLLECTIONS
    }
    for collection_name in PERSISTENT_COLLECTIONS:
        collections[collection_name] = _merge_collection_maps(
            current_collections.get(collection_name, {}),
            collections.get(collection_name, {}),
        )

    runtime_state = backup.get("runtime")
    is_full_state_backup = isinstance(runtime_state, dict)
    if is_full_state_backup:
        imported_settings = runtime_state.get("bot_settings")
        imported_batches = runtime_state.get("number_batches")
        if not isinstance(imported_settings, dict):
            raise ValueError("Full backup is missing bot settings.")
        if not isinstance(imported_batches, dict):
            raise ValueError("Full backup is missing number batches.")
        imported_runtime_maps = {
            "stex_assigned_numbers": runtime_state.get("stex_assigned_numbers", {}),
            "voltx_assigned_numbers": runtime_state.get("voltx_assigned_numbers", {}),
            "zenex_assigned_numbers": runtime_state.get("zenex_assigned_numbers", {}),
            "assigned_number_rates": runtime_state.get("assigned_number_rates", {}),
        }
        if any(not isinstance(value, dict) for value in imported_runtime_maps.values()):
            raise ValueError("Full backup contains invalid assignment data.")
        imported_used_numbers = runtime_state.get("used_numbers_list", [])
        imported_processed_otps = runtime_state.get("processed_otps", [])
        imported_recent_traffic = runtime_state.get("recent_traffic", [])
        if not isinstance(imported_used_numbers, list):
            raise ValueError("Full backup used_numbers_list is invalid.")
        if not isinstance(imported_processed_otps, list):
            raise ValueError("Full backup processed_otps is invalid.")
        if not isinstance(imported_recent_traffic, list):
            raise ValueError("Full backup recent_traffic is invalid.")

        # Merge settings/files so a restore never deletes data that exists only
        # in the current bot. Keep the configured owner as an emergency admin.
        bot_settings = _merge_settings(bot_settings, imported_settings)
        admins = bot_settings.get("admins", [])
        if not isinstance(admins, list):
            admins = []
        bot_settings["admins"] = list(dict.fromkeys(
            [int(item) if str(item).lstrip("-").isdigit() else item for item in admins]
            + ALL_ADMIN_IDS
        ))
        number_batches = _deduplicate_number_batches(
            _merge_number_batches(number_batches, imported_batches)
        )
        used_numbers_list = _unique_values(
            used_numbers_list, imported_used_numbers
        )
        stex_assigned_numbers = {
            **stex_assigned_numbers,
            **copy.deepcopy(imported_runtime_maps["stex_assigned_numbers"]),
        }
        voltx_assigned_numbers = {
            **voltx_assigned_numbers,
            **copy.deepcopy(imported_runtime_maps["voltx_assigned_numbers"]),
        }
        zenex_assigned_numbers = {
            **zenex_assigned_numbers,
            **copy.deepcopy(imported_runtime_maps["zenex_assigned_numbers"]),
        }
        assigned_number_rates = {
            **assigned_number_rates,
            **copy.deepcopy(imported_runtime_maps["assigned_number_rates"]),
        }
        total_uploaded_stats = max(
            int(total_uploaded_stats or 0),
            int(runtime_state.get("total_uploaded_stats", 0) or 0),
        )
        total_assigned_stats = max(
            int(total_assigned_stats or 0),
            int(runtime_state.get("total_assigned_stats", 0) or 0),
        )
        processed_otps = set(
            str(item) for item in _unique_values(
                sorted(processed_otps),
                imported_processed_otps,
            )
        )
        recent_traffic = _unique_values(
            recent_traffic, imported_recent_traffic
        )

        # These objects contain Telegram message IDs/provider sessions and are
        # intentionally reset instead of reviving stale live sessions.
        user_active_sessions.clear()
        user_cooldowns.clear()
        user_states.clear()
        temp_data.clear()
        with number_allocation_lock:
            claimed_numbers.clear()
        panel_sessions.clear()
        panel_api_cache.clear()

    _restore_rows_to_runtime({
        "Users": list(collections["users"].values()),
        "Withdrawals": list(collections["withdrawals"].values()),
        "History": list(collections["history"].values()),
    })
    user_banned_cache.clear()
    user_states.clear()
    temp_data.clear()
    user_cooldowns.clear()
    data_month = str(backup.get("data_month") or data_month_key())
    google_sheet_data_loaded = True
    google_sheet_load_error = ""
    if is_full_state_backup:
        # Save the merged runtime state. Existing settings are intentionally
        # retained; save_db updates only the current merged documents.
        save_db()
    save_local_db()
    return {
        "users": len(collections["users"]),
        "withdrawals": len(collections["withdrawals"]),
        "history": len(collections["history"]),
        "number_batches": len(number_batches),
        "full_state": is_full_state_backup,
    }


def delete_all_bot_data():
    """Reset operational data while keeping the owner able to open the bot."""
    global bot_settings, number_batches, total_uploaded_stats, total_assigned_stats
    global data_month, local_users, audit_history, all_known_users, claimed_numbers
    number_batches.clear()
    total_uploaded_stats = 0
    total_assigned_stats = 0
    used_numbers_list.clear()
    with number_allocation_lock:
        claimed_numbers.clear()
    stex_assigned_numbers.clear()
    voltx_assigned_numbers.clear()
    zenex_assigned_numbers.clear()
    assigned_number_rates.clear()
    processed_otps.clear()
    recent_traffic.clear()
    local_users.clear()
    audit_history.clear()
    all_known_users.clear()
    user_cache.clear()
    user_banned_cache.clear()
    pending_withdrawals.clear()
    user_active_sessions.clear()
    user_states.clear()
    temp_data.clear()
    user_cooldowns.clear()
    bot_settings = {
        "admins": ALL_ADMIN_IDS.copy(),
        "panels": [],
        "fw_groups": [],
        "otp_link": "https://t.me/your_otp_group",
        "withdraw_on": True,
        "join_notifications": {str(OWNER_ID): True},
        "min_withdraw": 30.0,
        "otp_reward": 0.1,
        "refer_reward": 0.2,
        "cooldown": 10,
        "num_req": 3,
        "num_share": 1,
        "support_link": "https://t.me/your_support",
        "w_methods": ["bKash", "Nagad"],
        "w_group": "",
        "fj_on": False,
        "fj_channels": [],
        "stex_keys": [],
        "voltx_keys": [],
        "zenex_keys": [],
        "search_countries": [],
        "voltx_search_countries": [],
        "zenex_search_countries": [],
        "stex_services": {},
        "voltx_services": {},
        "zenex_services": {},
        "premium_flags": {},
        "premium_apps": copy.deepcopy(DEFAULT_PREMIUM_APPS),
        "custom_messages": copy.deepcopy(DEFAULT_CUSTOM_MESSAGES),
    }
    data_month = data_month_key()
    for collection_name in ("users", "history", "withdrawals", "settings"):
        _clear_database_collection(collection_name)
    save_local_db()
    save_db()
    _save_users_list()


EXPORT_USER_FIELDS = [
    "user_name", "username", "user_id", "balance", "otp", "total_refers",
    "total_otps", "banned", "verified", "language", "created_at",
    "updated_at", "referred_by", "ref_paid"
]
EXPORT_HISTORY_FIELDS = [
    "event_id", "timestamp", "user_id", "event_type", "amount", "status",
    "method", "request_id", "balance_after", "payment_number", "message"
]


def _export_value(value):
    if value is None:
        return ""
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def collect_export_rows():
    users = []
    history = []
    if db:
        try:
            for snapshot in db.collection("users").stream():
                row = snapshot.to_dict()
                if _is_group_or_channel_record(row):
                    continue
                row["user_id"] = row.get("user_id", snapshot.id)
                row["user_name"] = row.get("user_name", row.get("full_name", ""))
                row["username"] = _normalize_username(row.get("username", ""))
                users.append({key: row.get(key, "") for key in EXPORT_USER_FIELDS})
        except Exception:
            pass
        try:
            for snapshot in db.collection("history").order_by("timestamp", direction="DESCENDING").stream():
                row = snapshot.to_dict()
                history.append({key: row.get(key, "") for key in EXPORT_HISTORY_FIELDS})
        except Exception:
            pass
    else:
        for key, row in local_users.items():
            row = dict(row)
            if _is_group_or_channel_record(row):
                continue
            row["user_id"] = row.get("user_id", key)
            row["user_name"] = row.get("user_name", row.get("full_name", ""))
            row["username"] = _normalize_username(row.get("username", ""))
            users.append({field: row.get(field, "") for field in EXPORT_USER_FIELDS})
        history = [
            {field: row.get(field, "") for field in EXPORT_HISTORY_FIELDS}
            for row in audit_history
        ]

    users = list(_deduplicate_collection_rows(users, "users").values())
    history = list(_deduplicate_collection_rows(history, "history").values())
    users.sort(key=lambda row: str(row.get("user_id", "")))
    history.sort(key=lambda row: str(row.get("event_id", "")))
    return users, history


def _make_csv(headers, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _export_value(row.get(key, "")) for key in headers})
    return output.getvalue().encode("utf-8-sig")


def _xlsx_cell(value, reference="A1"):
    text = xml_escape(_export_value(value))
    return f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>'


def _xlsx_sheet(headers, rows):
    all_rows = [headers] + [[row.get(key, "") for key in headers] for row in rows]
    body = []
    for row_number, row in enumerate(all_rows, 1):
        cells = ""
        for column_number, value in enumerate(row):
            number = column_number + 1
            letters = ""
            while number:
                number, remainder = divmod(number - 1, 26)
                letters = chr(65 + remainder) + letters
            cells += _xlsx_cell(value, f"{letters}{row_number}")
        body.append(f'<row r="{row_number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(body) + '</sheetData></worksheet>'
    )


def make_xlsx(users, history, withdrawals=None):
    withdrawals = withdrawals or []
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Users" sheetId="1" r:id="rId1"/>'
        '<sheet name="Withdrawals" sheetId="2" r:id="rId2"/>'
        '<sheet name="History" sheetId="3" r:id="rId3"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet(EXPORT_USER_FIELDS, users))
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            _xlsx_sheet(
                ["request_id", "user_id", "amount", "method", "number",
                 "full_name", "status", "timestamp", "balance_after"],
                withdrawals,
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet3.xml",
            _xlsx_sheet(EXPORT_HISTORY_FIELDS, history),
        )
    return output.getvalue()


def _xlsx_column_number(cell_reference):
    letters = re.match(r"([A-Z]+)", str(cell_reference or "").upper())
    if not letters:
        return 0
    number = 0
    for char in letters.group(1):
        number = number * 26 + ord(char) - ord("A") + 1
    return number - 1


def _xlsx_xml_text(node):
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _read_xlsx_sheets(raw_bytes):
    """Read normal Google-exported XLSX files without openpyxl."""
    namespace = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as archive:
        names = set(archive.namelist())
        shared_strings = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                _xlsx_xml_text(item)
                for item in root.findall("main:si", namespace)
            ]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationship_root = ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        relationships = {}
        for rel in relationship_root.findall("pkg:Relationship", namespace):
            target = rel.attrib.get("Target", "")
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            relationships[rel.attrib.get("Id", "")] = target

        result = {}
        for sheet in workbook.findall("main:sheets/main:sheet", namespace):
            title = sheet.attrib.get("name", "Sheet")
            relation_id = sheet.attrib.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                "",
            )
            target = relationships.get(relation_id)
            if not target or target not in names:
                continue
            root = ET.fromstring(archive.read(target))
            matrix = []
            for row in root.findall(".//main:sheetData/main:row", namespace):
                values = {}
                for cell in row.findall("main:c", namespace):
                    cell_type = cell.attrib.get("t", "")
                    value_node = cell.find("main:v", namespace)
                    if cell_type == "inlineStr":
                        value = _xlsx_xml_text(cell.find("main:is", namespace))
                    else:
                        value = _xlsx_xml_text(value_node)
                        if cell_type == "s" and value.isdigit():
                            index = int(value)
                            value = (
                                shared_strings[index]
                                if index < len(shared_strings) else ""
                            )
                    values[_xlsx_column_number(cell.attrib.get("r", ""))] = value
                if values:
                    width = max(values) + 1
                    matrix.append([values.get(index, "") for index in range(width)])
            if not matrix:
                result[title] = []
                continue
            headers = [str(value).strip() for value in matrix[0]]
            rows = []
            for values in matrix[1:]:
                if not any(str(value).strip() for value in values):
                    continue
                rows.append({
                    header: values[index] if index < len(values) else ""
                    for index, header in enumerate(headers) if header
                })
            result[title] = rows
    return result


def xlsx_to_backup(raw_bytes):
    sheets = _read_xlsx_sheets(raw_bytes)
    collections = {"users": {}, "withdrawals": {}, "history": {}}
    for title, rows in sheets.items():
        lowered = str(title).strip().lower()
        if lowered in ("users", "user", "user data"):
            target, id_field = "users", "user_id"
        elif lowered in ("withdrawals", "withdrawal", "withdraw history"):
            target, id_field = "withdrawals", "request_id"
        elif lowered in ("history", "events", "transactions"):
            target, id_field = "history", "event_id"
        elif rows and "request_id" in rows[0]:
            target, id_field = "withdrawals", "request_id"
        elif rows and "user_id" in rows[0]:
            target, id_field = "users", "user_id"
        else:
            continue
        for index, row in enumerate(rows):
            key = str(row.get(id_field) or f"RESTORED_{target}_{index + 1}")
            collections[target][key] = row
    if not any(collections.values()):
        raise ValueError("No Users, Withdrawals or History sheet was found.")
    return {
        "backup_format": "google-sheets-xlsx",
        "backup_version": 2,
        "created_at": iso_now(),
        "collections": collections,
    }


def csv_to_backup(raw_bytes):
    text = raw_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("The CSV file contains no rows.")
    headers = set(rows[0])
    if "request_id" in headers:
        target, id_field = "withdrawals", "request_id"
    elif "event_type" in headers or "event_id" in headers:
        target, id_field = "history", "event_id"
    else:
        target, id_field = "users", "user_id"
    return {
        "backup_format": "google-sheets-csv",
        "backup_version": 2,
        "created_at": iso_now(),
        "collections": {
            "users": {
                str(row.get("user_id") or f"RESTORED_{index + 1}"): row
                for index, row in enumerate(rows)
            } if target == "users" else {},
            "withdrawals": {
                str(row.get("request_id") or f"RESTORED_{index + 1}"): row
                for index, row in enumerate(rows)
            } if target == "withdrawals" else {},
            "history": {
                str(row.get("event_id") or f"RESTORED_{index + 1}"): row
                for index, row in enumerate(rows)
            } if target == "history" else {},
        },
    }


def _pdf_safe(text):
    text = unicodedata.normalize("NFKD", _export_value(text))
    text = text.encode("ascii", "replace").decode("ascii")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(users, history):
    lines = [
        "BOT DATA EXPORT",
        f"Generated: {iso_now()}",
        f"Users: {len(users)} | History events: {len(history)}",
        "",
        "USERS"
    ]
    lines.append(" | ".join(EXPORT_USER_FIELDS))
    for row in users:
        lines.append(" | ".join(_export_value(row.get(key, "")) for key in EXPORT_USER_FIELDS))
    lines.extend(["", "HISTORY"])
    lines.append(" | ".join(EXPORT_HISTORY_FIELDS))
    for row in history:
        lines.append(" | ".join(_export_value(row.get(key, "")) for key in EXPORT_HISTORY_FIELDS))

    lines = [_pdf_safe(line[:150]) for line in lines]
    page_lines = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [["No data"]]
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
    ]
    page_ids = []
    for page in page_lines:
        stream_lines = ["BT", "/F1 7 Tf", "28 805 Td", "9 TL"]
        for line in page:
            stream_lines.append(f"({_pdf_safe(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        content_id = len(objects) + 1
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream")
        page_id = len(objects) + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        page_ids.append(page_id)
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] /Count {len(page_ids)} >>"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj.encode("latin-1", "replace"))
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def send_data_export(chat_id):
    users, history = collect_export_rows()
    withdrawals = _google_sheet_rows().get("Withdrawals", [])
    if not users and not history:
        send_message(chat_id, render_body_text("❌ No user/history data is available for export."))
        return
    month = data_month_key()
    send_document(chat_id, f"bot_data_{month}.csv", _make_csv(EXPORT_USER_FIELDS, users))
    send_document(chat_id, f"bot_history_{month}.csv", _make_csv(EXPORT_HISTORY_FIELDS, history))
    send_document(chat_id, f"bot_data_{month}.xlsx", make_xlsx(users, history, withdrawals))
    send_document(chat_id, f"bot_data_{month}.pdf", make_pdf(users, history))
    send_message(chat_id, render_body_text(
        f"{PEM['ok']} <b>Export complete.</b>\n"
        f"Users: {len(users)} | History events: {len(history)}\n"
        "CSV, Excel and PDF files were sent."
    ))

all_known_users = set()

def sync_users_list():
    global all_known_users
    try:
        all_known_users.clear()
        if db:
            for doc in db.collection('users').select([]).stream():
                all_known_users.add(doc.id)
        else:
            all_known_users.update(str(uid) for uid in local_users.keys())
    except: pass

threading.Thread(target=sync_users_list, daemon=True).start()

def _save_users_list():
    # User IDs are already kept in the bot database; no extra local file.
    return

def register_user_local(uid):
    uid_str = str(uid)
    if uid_str not in all_known_users:
        # users_list.json can be stale after a restart, so avoid treating an
        # already-persisted user as a new joiner.
        already_persisted = uid_str in local_users
        if db and not already_persisted:
            try:
                already_persisted = db.collection("users").document(uid_str).get().exists
            except Exception:
                pass
        all_known_users.add(uid_str)
        threading.Thread(target=_save_users_list, daemon=True).start()
        return not already_persisted
    return False


def get_join_notification_status(admin_id):
    settings = bot_settings.setdefault("join_notifications", {})
    key = str(admin_id)
    if key not in settings:
        settings[key] = True
    return bool(settings[key])


def notify_admins_new_user(msg, user_id):
    """Notify each admin independently according to their own preference."""
    from_user = msg.get("from", {})
    full_name = " ".join(
        part for part in (from_user.get("first_name", ""), from_user.get("last_name", ""))
        if part
    ).strip() or "Unknown user"
    username = from_user.get("username")
    username_text = f"@{username}" if username else "No username"
    text = (
        "👤 <b>NEW USER JOINED</b>\n\n"
        f"Name: {html.escape(full_name)}\n"
        f"Username: {html.escape(username_text)}\n"
        f"User ID: <code>{user_id}</code>"
    )
    for admin_id in get_configured_admin_ids():
        if get_join_notification_status(admin_id):
            send_message(admin_id, render_body_text(text))

def broadcast_copymessage(from_chat_id, msg_id):
    success = 0
    failed = 0
    users = list(all_known_users)
    
    b_session = requests.Session()
    url = f"{BASE_URL}/copyMessage"
    
    for user_id in users:
        payload = {"chat_id": user_id, "from_chat_id": from_chat_id, "message_id": msg_id}
        try:
            res = b_session.post(url, json=payload, timeout=5).json()
            if res.get("ok"): success += 1
            else: failed += 1
        except:
            failed += 1
        time.sleep(0.035)
        
    send_message(from_chat_id, render_body_text(f"📢 <b>Broadcast Completed!</b>\n✅ Success: {success}\n❌ Failed: {failed}\n👥 Total Sent: {len(users)}"))

def render_body_text(text):
    if not text: return str(text)
    parts = re.split(r'(<tg-emoji.*?</tg-emoji>)', str(text))
    for i in range(len(parts)):
        if not parts[i].startswith('<tg-emoji'):
            for normal_emj, prem_id in GLOBAL_BODY_EMOJIS.items():
                if normal_emj in parts[i]:
                    parts[i] = parts[i].replace(normal_emj, f'<tg-emoji emoji-id="{prem_id}">{normal_emj}</tg-emoji>')
    return "".join(parts)

def extract_premium_html(msg):
    text = msg.get("text", msg.get("caption", ""))
    entities = msg.get("entities", msg.get("caption_entities", []))
    if not entities: return text
    try:
        b_text = text.encode('utf-16-le')
        c_entities = [e for e in entities if e.get("type") == "custom_emoji"]
        c_entities.sort(key=lambda x: x["offset"], reverse=True)
        for ent in c_entities:
            offset = ent["offset"] * 2
            length = ent["length"] * 2
            eid = ent["custom_emoji_id"]
            emoji_char = b_text[offset:offset+length].decode('utf-16-le')
            html_tag = f'<tg-emoji emoji-id="{eid}">{emoji_char}</tg-emoji>'
            replacement = html_tag.encode('utf-16-le')
            b_text = b_text[:offset] + replacement + b_text[offset+length:]
        return b_text.decode('utf-16-le')
    except Exception as e:
        return text 

def get_flag_info_from_num(num):
    clean = num.replace("+", "").replace(" ", "")
    sorted_codes = sorted(bot_settings.get("premium_flags", {}).keys(), key=len, reverse=True)
    for code in sorted_codes:
        if clean.startswith(code):
            data = bot_settings["premium_flags"][code]
            return data["char"], data.get("iso", "XX"), data.get("id")
    return "🌍", "XX", None

def get_flag_and_code(num):
    char, iso, _ = get_flag_info_from_num(num)
    return char, iso

def get_flag_info_html(num_or_iso, return_full_name=False):
    if len(num_or_iso) == 2:
        for code, data in bot_settings.get("premium_flags", {}).items():
            if data.get("iso") == num_or_iso:
                eid = data.get("id")
                char = data.get("char")
                name = data.get("name", num_or_iso)
                if return_full_name: return name
                if eid: return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
                return char
        if return_full_name: return num_or_iso
        return "🌍"
        
    char, _, eid = get_flag_info_from_num(num_or_iso)
    if return_full_name:
        for code, data in bot_settings.get("premium_flags", {}).items():
            clean = num_or_iso.replace("+", "").replace(" ", "")
            if clean.startswith(code): return data.get("name", num_or_iso)
        return num_or_iso
        
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
    return char

def mask_number(num):
    """Show a compact country-prefix/GX/last-three group label."""
    value = str(num or "").strip()
    clean = re.sub(r"\D", "", value)
    if not clean:
        return value
    country_prefix = ""
    for raw_code in sorted(
        bot_settings.get("premium_flags", {}).keys(),
        key=lambda code: len(re.sub(r"\D", "", str(code))),
        reverse=True,
    ):
        code = re.sub(r"\D", "", str(raw_code))
        if code and clean.startswith(code):
            country_prefix = code
            break
    if not country_prefix:
        country_prefix = clean[:3] if len(clean) > 3 else clean
    last_three = clean[-3:] if len(clean) >= 3 else clean
    return f"{country_prefix}GX{last_three}"

LANG_MAP = {
    "#EN": "English", "#BN": "Bengali", "#AR": "Arabic", "#HI": "Hindi", 
    "#PA": "Punjabi", "#GU": "Gujarati", "#OR": "Odia", "#TA": "Tamil", 
    "#TE": "Telugu", "#KN": "Kannada", "#ML": "Malayalam", "#SI": "Sinhala", 
    "#TH": "Thai", "#LO": "Lao", "#BO": "Tibetan", "#MY": "Burmese", 
    "#AM": "Amharic", "#KM": "Khmer", "#KA": "Georgian", "#HY": "Armenian", 
    "#HE": "Hebrew", "#EL": "Greek", "#RU": "Russian", "#ZH": "Chinese", 
    "#JA": "Japanese", "#KO": "Korean", "#ID": "Indonesian", "#MS": "Malay", 
    "#VN": "Vietnamese", "#TL": "Filipino", "#ES": "Spanish", "#PT": "Portuguese", 
    "#FR": "French", "#DE": "German", "#IT": "Italian", "#PL": "Polish", 
    "#TR": "Turkish", "#NL": "Dutch", "#SV": "Swedish", "#DA": "Danish", 
    "#NO": "Norwegian", "#FI": "Finnish", "#CS": "Czech", "#SK": "Slovak", 
    "#HU": "Hungarian", "#RO": "Romanian", "#HR": "Croatian", "#BG": "Bulgarian", 
    "#UK": "Ukrainian", "#SW": "Swahili", "#AF": "Afrikaans"
}

# ==========================================
# ADVANCED SERVICE & LANGUAGE DETECTION
# ==========================================

SERVICE_SMS_KEYWORDS = {
    "whatsapp": ["whatsapp", "whatsa", "whatsap", "whats", "whatsapp business", "whatsapp me", "whatsapp code", "whatsap", "واتساب", "واتساپ", "واٹس ایپ", "व्हाट्सएप", "वाट्सएप", "वॉट्सऐप", "व्हाट्सप्प", "হোয়াটসঅ্যাপ", "হোটসঅ্যাপ", "ватсап", "уотсап", "вотсап", "ватс апп", "వాట్సాప్", "വാട്‌സ്ആപ്പ്", "வாட்ஸ்அப்", "ವಾಟ್ಸಾಪ್", "વોટ્સએપ", "ਵਟਸਐਪ", "ହ୍ଵାଟସ୍ ଆପ୍", "වට්ස්ඇප්", "วอตส์แอปป์", "วอทส์แอพ", "ဝက်စ်အက်ပ်", "វ៉តសាប់", "ວອດແອັບ", "ワッツアップ", "왓츠앱", "whatsapp的", "whatsapp验证码", "וואטסאפ", "γουάτσαπ", "ዋትስአፕ", "ვოთსაფი", "վոթսափ"],
    "facebook": ["facebook", "fb", "meta", "fbook", "fb code", "facebook code", "فيسبوك", "فيس بوك"],
    "instagram": ["instagram", "insta", "ig", "ig code", "instagram code", "انستغرام", "انستقرام"],
    "telegram": ["telegram", "tg", "tele", "telegram code", "tg code", "t.me", "تيليجرام", "تليجرام"],
    "tiktok": ["tiktok", "tik tok", "tikvideo", "tiktok code", "tik code", "تيك توك"],
    "snapchat": ["snapchat", "snap", "snap code", "سناب شات"],
    "twitter": ["twitter", "x.com", "x code", "twitter code", "تويتر"],
    "discord": ["discord", "discord code", "ديسكورد"],
    "viber": ["viber", "viber code", "فايبر"],
    "line": ["line", "line code", "line verification", "لاين"],
    "wechat": ["wechat", "we chat", "wechat code", "وي تشات"],
    "signal": ["signal", "signal code", "سيجنال"],
    "linkedin": ["linkedin", "linked in", "لينكد إن"],
    "imo": ["imo", "imo code", "imo verification", "ايمو"],
    "kakaotalk": ["kakao", "kakaotalk", "كاكاو"],
    "qq": ["qq", "tencent qq"],
    "vk": ["vk", "vkontakte"],
    "google": ["google", "gmail", "youtube", "g-", "google voice", "جوجل", "غوغل"],
    "microsoft": ["microsoft", "ms", "outlook", "live.com", "hotmail"],
    "apple": ["apple", "icloud", "itunes", "apple id"],
    "yahoo": ["yahoo", "yahoo code", "ymail"],
    "protonmail": ["proton", "protonmail"],
    "binance": ["binance", "bnb", "binances"],
    "coinbase": ["coinbase"],
    "okx": ["okx", "okex"],
    "kucoin": ["kucoin"],
    "bybit": ["bybit"],
    "huobi": ["huobi", "htx"],
    "mexc": ["mexc"],
    "trustwallet": ["trust wallet", "trustwallet"],
    "bkash": ["bkash", "b-kash", "bkash code"],
    "nagad": ["nagad", "nagad code"],
    "rocket": ["rocket", "dutch bangla"],
    "upay": ["upay", "upay code"],
    "paypal": ["paypal", "pay pal"],
    "paytm": ["paytm"],
    "cashapp": ["cash app", "cashapp"],
    "wise": ["wise", "transferwise"],
    "amazon": ["amazon", "amzn", "amazon code"],
    "ebay": ["ebay"],
    "aliexpress": ["aliexpress", "ali express"],
    "alibaba": ["alibaba"],
    "daraz": ["daraz", "daraz code"],
    "foodpanda": ["foodpanda", "food panda"],
    "uber": ["uber", "uber code", "uber verification", "uber eats"],
    "pathao": ["pathao", "pathao ride"],
    "netflix": ["netflix", "netflix code"],
    "spotify": ["spotify", "spotify code"],
    "steam": ["steam", "steam guard"],
    "epicgames": ["epic games", "epicgames"],
    "roblox": ["roblox", "roblox code"],
    "riotgames": ["riot", "riot games", "valorant", "league of legends"],
    "garena": ["garena", "free fire", "freefire"],
    "playstation": ["playstation", "psn"],
    "1xbet": ["1xbet", "1x bet"],
    "melbet": ["melbet", "melbet code"],
    "linebet": ["linebet"],
    "bet365": ["bet365"],
    "megapari": ["megapari"],
    "tinder": ["tinder", "tinder code"],
    "bumble": ["bumble"],
    "badoo": ["badoo"]
}

def detect_service(text):
    text_lower = str(text).lower()
    for service_key, keywords in SERVICE_SMS_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return service_key.upper()
    return None

def get_service_info_html(service_text, msg_text=""):
    s = str(service_text).upper().strip()
    m = str(msg_text).lower().strip()
    apps = bot_settings.get("premium_apps", {})
    
    detected_service = s
    if m:
        for service_key, keywords in SERVICE_SMS_KEYWORDS.items():
            for kw in keywords:
                if kw in m:
                    detected_service = service_key.upper()
                    break
            if detected_service != s: break

    clean_s = re.sub(r'[^\w\s]', '', detected_service).strip()
    
    for app_name, data in apps.items():
        if app_name == detected_service or app_name == clean_s or app_name in detected_service or detected_service in app_name:
            full_name = data.get("name", app_name.title())
            char = data.get("char", "📱")
            eid = data.get("id")
            if eid: return full_name, f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
            return full_name, char
            
    return detected_service.title(), "📱"

def get_service_icon_id(service_text, msg_text=""):
    """Return the premium icon ID belonging to a service button."""
    app_full_name, _ = get_service_info_html(service_text, msg_text)
    normalized_name = re.sub(r"[^\w\s]", "", str(app_full_name)).strip().upper()
    normalized_service = re.sub(r"[^\w\s]", "", str(service_text)).strip().upper()
    for app_key, app_data in bot_settings.get("premium_apps", {}).items():
        candidates = {
            str(app_key).replace("_", " ").strip().upper(),
            str(app_data.get("name", "")).strip().upper(),
        }
        if normalized_name in candidates or normalized_service in candidates:
            return app_data.get("id") or "5190645917711114179"
    return "5190645917711114179"

def detect_language(text):
    if not text: return "#EN"
    text_str = str(text)

    if any('\u0600' <= c <= '\u06ff' for c in text_str): return "#AR"
    if any('\u0980' <= c <= '\u09ff' for c in text_str): return "#BN"
    if any('\u0900' <= c <= '\u097f' for c in text_str): return "#HI"
    if any('\u0a00' <= c <= '\u0a7f' for c in text_str): return "#PA"
    if any('\u0a80' <= c <= '\u0aff' for c in text_str): return "#GU"
    if any('\u0b00' <= c <= '\u0b7f' for c in text_str): return "#OR"
    if any('\u0b80' <= c <= '\u0bff' for c in text_str): return "#TA"
    if any('\u0c00' <= c <= '\u0c7f' for c in text_str): return "#TE"
    if any('\u0c80' <= c <= '\u0cff' for c in text_str): return "#KN"
    if any('\u0d00' <= c <= '\u0d7f' for c in text_str): return "#ML"
    if any('\u0d80' <= c <= '\u0dff' for c in text_str): return "#SI"
    if any('\u0e00' <= c <= '\u0e7f' for c in text_str): return "#TH"
    if any('\u0e80' <= c <= '\u0eff' for c in text_str): return "#LO"
    if any('\u0f00' <= c <= '\u0fff' for c in text_str): return "#BO"
    if any('\u1000' <= c <= '\u109f' for c in text_str): return "#MY"
    if any('\u1200' <= c <= '\u137f' for c in text_str): return "#AM"
    if any('\u1780' <= c <= '\u17ff' for c in text_str): return "#KM"
    if any('\u10a0' <= c <= '\u10ff' for c in text_str): return "#KA"
    if any('\u0530' <= c <= '\u058f' for c in text_str): return "#HY"
    if any('\u0590' <= c <= '\u05ff' for c in text_str): return "#HE"
    if any('\u0370' <= c <= '\u03ff' for c in text_str): return "#EL"
    if any('\u0400' <= c <= '\u04ff' for c in text_str): return "#RU"
    if any('\u4e00' <= c <= '\u9fff' for c in text_str): return "#ZH"
    if any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in text_str): return "#JA"
    if any('\uac00' <= c <= '\ud7af' for c in text_str): return "#KO"

    text_lower = text_str.lower()
    
    if any(w in text_lower for w in ["kode verifikasi", "jangan bagikan", "rahasia"]): return "#ID"
    if any(w in text_lower for w in ["kod pengesahan", "jangan kongsi"]): return "#MS"
    if any(w in text_lower for w in ["mã của bạn", "không chia sẻ", "mã xác minh"]): return "#VN"
    if any(w in text_lower for w in ["ang iyong code", "huwag ibahagi"]): return "#TL"
    if any(w in text_lower for w in ["código", "tu código", "verificación", "no compartas"]): return "#ES"
    if any(w in text_lower for w in ["seu código", "código de verificação", "não compartilhe"]): return "#PT"
    if any(w in text_lower for w in ["code secret", "ne partagez pas", "votre code"]): return "#FR"
    if any(w in text_lower for w in ["dein code", "bestätigungscode", "nicht teilen"]): return "#DE"
    if any(w in text_lower for w in ["il tuo codice", "codice di verifica", "non condividere"]): return "#IT"
    if any(w in text_lower for w in ["twój kod", "nie udostępniaj", "kod weryfikacyjny"]): return "#PL"
    if any(w in text_lower for w in ["doğrulama kodu", "paylaşmayın", "onay kodu"]): return "#TR"
    if any(w in text_lower for w in ["jouw code", "verificatiecode", "niet delen"]): return "#NL"
    if any(w in text_lower for w in ["din kod", "verifieringskod", "dela inte"]): return "#SV"
    if any(w in text_lower for w in ["bekræftelseskode", "del ikke"]): return "#DA"
    if any(w in text_lower for w in ["bekreftelseskode", "ikke del"]): return "#NO"
    if any(w in text_lower for w in ["vahvistuskoodi", "älä jaa"]): return "#FI"
    if any(w in text_lower for w in ["váš kód", "ověřovací kód", "nesdílejte"]): return "#CS"
    if any(w in text_lower for w in ["overovací kód", "nezdieľajte"]): return "#SK"
    if any(w in text_lower for w in ["ellenőrző kód", "ne oszd meg"]): return "#HU"
    if any(w in text_lower for w in ["codul tău", "codul de verificare", "nu partaja"]): return "#RO"
    if any(w in text_lower for w in ["kontrolni kod", "kod za potvrdu", "ne delite"]): return "#HR"
    if any(w in text_lower for w in ["код за потвърждение", "не споделяйте"]): return "#BG"
    if any(w in text_lower for w in ["ваш код", "код підтвердження"]): return "#UK"
    if any(w in text_lower for w in ["msimbo wako", "usishiriki"]): return "#SW"
    if any(w in text_lower for w in ["verifikasiekode", "moenie deel nie"]): return "#AF"
    
    return "#EN"

def parse_chat_id(text):
    text = text.strip()
    if text.startswith("-100") or (text.startswith("-") and text[1:].isdigit()):
        return text
    if "t.me/" in text:
        parts = text.split("/")
        username = parts[-1]
        if username: return "@" + username if not username.startswith("@") else username
    if text.startswith("@"):
        return text
    return "@" + text

def is_admin(user_id):
    return user_id in get_configured_admin_ids()

def check_force_join(user_id):
    if not bot_settings["fj_on"] or not bot_settings["fj_channels"]: return True
    if is_admin(user_id): return True
    for ch in bot_settings["fj_channels"]:
        res = api_call("getChatMember", {"chat_id": ch, "user_id": user_id})
        if res.get("ok") and res["result"]["status"] not in ["left", "kicked"]: continue
        else: return False
    return True

def send_force_join_msg(chat_id):
    kb = []
    for ch in bot_settings["fj_channels"]:
        url = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        kb.append([{"text": f"Join Channel", "icon_custom_emoji_id": "5789428375261023681", "url": url, "style": "primary"}])
    kb.append([{"text": "Check Joined", "icon_custom_emoji_id": "5352694861990501856", "callback_data": "check_fj", "style": "success"}])
    send_message(chat_id, render_body_text(f"{PEM['warn']} <b>Please join our channels to use the bot!</b>"), reply_markup={"inline_keyboard": kb})

def is_user_banned(user_id):
    if is_admin(user_id): return False
    if user_id in user_banned_cache and time.time() - user_banned_cache[user_id]['time'] < 60:
        return user_banned_cache[user_id]['banned']
    banned = False
    if db:
        try:
            doc = db.collection('users').document(str(user_id)).get()
            banned = doc.exists and doc.to_dict().get("banned", False)
        except: pass
    user_banned_cache[user_id] = {'banned': banned, 'time': time.time()}
    return banned

# ==========================================
# Captcha Auto Login & Parsing Core
# ==========================================
def extract_otp_code(text):
    clean_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', str(text))

    multi_part = re.search(r'(\d{3}[-\s]+\d{3})|(\d{2}[-\s]+\d{2}[-\s]+\d{2})', clean_text)
    if multi_part:
        return multi_part.group(0).replace(" ", "")

    otp_keywords = ['code', 'is', 'otp', 'pin', 'verification', 'auth', 'কোড', 'رمز', 'your code']
    keywords_pattern = '|'.join(otp_keywords)
    keyword_match = re.search(rf'(?:{keywords_pattern})\s*(?:is|:|-|=)?\s*([a-z0-9]{{4,10}})', clean_text, re.I)
    if keyword_match and keyword_match.group(1).isdigit():
        return keyword_match.group(1)
        
    keyword_match_rev = re.search(rf'([a-z0-9]{{4,10}})\s*(?:is your|is the|কোড)', clean_text, re.I)
    if keyword_match_rev and keyword_match_rev.group(1).isdigit():
        return keyword_match_rev.group(1)

    g_match = re.search(r'G-(\d{6})', clean_text, re.IGNORECASE)
    if g_match: return g_match.group(1)

    digit_matches = re.findall(r'(?<!\d)\d{4,8}(?!\d)', clean_text)
    if digit_matches: return digit_matches[0]

    return None

def parse_panel_response(response_text, p_config=None):
    results = []
    p_type = p_config.get("type", "API Panel") if p_config else "API Panel"
    
    n_col_name = p_config.get("num_col_name", "number").lower() if p_config else "number"
    m_col_name = p_config.get("msg_col_name", "message").lower() if p_config else "message"
    n_idx = int(p_config.get("num_col_idx", 1)) - 1 if p_config and p_config.get("num_col_idx") else 1
    m_idx = int(p_config.get("msg_col_idx", 2)) - 1 if p_config and p_config.get("msg_col_idx") else 2

    if p_type == "Auto Captcha Panel":
        try:
            soup = BeautifulSoup(response_text, 'html.parser')
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                if not rows: continue
                
                final_n_idx = n_idx
                final_m_idx = m_idx
                
                header_cells = rows[0].find_all(['th', 'td'])
                for i, cell in enumerate(header_cells):
                    c_text = cell.get_text(strip=True).lower()
                    if n_col_name in c_text: final_n_idx = i
                    if m_col_name in c_text: final_m_idx = i

                for row in rows:
                    cols = row.find_all(['td', 'th'])
                    
                    if all(c.name == 'th' for c in cols): continue
                    
                    if len(cols) > max(final_n_idx, final_m_idx):
                        num_text = cols[final_n_idx].get_text(separator=" ", strip=True)
                        msg_text = cols[final_m_idx].get_text(separator=" ", strip=True)
                        
                        clean_num = re.sub(r'\D', '', num_text)
                        
                        if clean_num and 5 <= len(clean_num) <= 18:
                            otp = extract_otp_code(msg_text)
                            if otp and len(msg_text) > 4:
                                results.append({"number": clean_num, "message": msg_text, "otp": otp})
        except Exception as e:
            pass
    else:
        try:
            data = json.loads(response_text)
            temp_results = []
            
            def process_item(item):
                pot_nums_list = []
                pot_msg = None
                values = []
                
                if isinstance(item, dict):
                    lower_keys = {str(k).lower(): v for k, v in item.items()}
                    for k in [
                        "number", "num", "phone", "phone_number", "msisdn",
                        "mobile", "mobile_number", "telephone", "tel",
                        "full_number", "national_number", "no_plus_number",
                        "receiver", "recipient", "to_number",
                    ]:
                        if k in lower_keys:
                            clean_val = re.sub(r'\D', '', str(lower_keys[k]))
                            if 5 <= len(clean_val) <= 18:
                                if clean_val not in pot_nums_list: pot_nums_list.append(clean_val)
                    for k in [
                        "message", "msg", "sms", "sms_text", "content",
                        "text", "body", "otp_message",
                    ]:
                        if k in lower_keys:
                            val = str(lower_keys[k])
                            if len(val) > 4:
                                pot_msg = val
                                break
                    values = list(item.values())
                elif isinstance(item, list):
                    values = item

                for v in values:
                    if isinstance(v, (dict, list)) or v is None: continue
                    v_str = str(v).strip()
                    
                    clean_v = re.sub(r'\D', '', v_str)
                    if 7 <= len(clean_v) <= 18 and not re.search(r'[a-zA-Z]', v_str):
                        if not re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', v_str) and not re.search(r'\d{2}:\d{2}:\d{2}', v_str) and "." not in v_str:
                            if clean_v not in pot_nums_list:
                                pot_nums_list.append(clean_v)
                    
                    if len(v_str) > 4 and not v_str.isdigit():
                        if extract_otp_code(v_str):
                            if pot_msg is None or len(v_str) > len(pot_msg):
                                pot_msg = v_str
                                
                pot_num = None
                if pot_nums_list:
                    matched_user_num = None
                    for n in pot_nums_list:
                        if n in stex_assigned_numbers or any(n in str(key) for key in stex_assigned_numbers.keys()):
                            matched_user_num = n
                            break
                    
                    if matched_user_num:
                        pot_num = matched_user_num
                    elif len(pot_nums_list) >= 2:
                        pot_num = pot_nums_list[1]
                    else:
                        pot_num = pot_nums_list[0]
                            
                if pot_num and pot_msg:
                    otp = extract_otp_code(pot_msg)
                    if otp:
                        temp_results.append({"number": pot_num, "message": pot_msg, "otp": otp})
                        
            def traverse_json(node):
                if isinstance(node, list):
                    if len(node) > 0 and not isinstance(node[0], (dict, list)):
                        process_item(node)
                    for child in node:
                        if isinstance(child, (dict, list)):
                            traverse_json(child)
                elif isinstance(node, dict):
                    process_item(node)
                    for val in node.values():
                        if isinstance(val, (dict, list)):
                            traverse_json(val)

            traverse_json(data)
            
            seen = set()
            for r in temp_results:
                uid = f"{r['number']}_{r['otp']}"
                if uid not in seen:
                    seen.add(uid)
                    results.append(r)
        except: pass
        
    # Some providers use a different key spelling (for example
    # phone_number/sms_text). Re-run through the strict explicit-field parser
    # as a fallback, but only keep rows that contain a real OTP.
    if not results:
        for item in parse_panel_number_response(response_text, p_config):
            if item.get("otp"):
                results.append({
                    "number": item["number"],
                    "message": item.get("message", ""),
                    "otp": item["otp"],
                })
    return results

def attempt_auto_login(p, idx):
    login_url = p.get("login_url", "").strip()
    if not login_url.startswith("http"):
        login_url = "http://" + login_url
        
    if not login_url.lower().endswith('/login') and not login_url.lower().endswith('.php'):
        login_url = f"{login_url.rstrip('/')}/login"
        
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    })
    
    try:
        res = session.get(login_url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        all_text = res.text
        
        captcha_match = re.search(r'(\d+\s*[\+\-\*]\s*\d+)\s*[=\?:]', all_text)
        if not captcha_match:
            captcha_match = re.search(r'what is\s*(\d+\s*[\+\-\*]\s*\d+)', all_text, re.I)
        if not captcha_match:
            elements = soup.find_all(["label", "div", "span", "p", "strong"])
            for el in elements:
                txt = el.get_text(separator=" ", strip=True)
                if any(op in txt for op in ["+", "-", "*"]):
                    m = re.search(r'(\d+\s*[\+\-\*]\s*\d+)', txt)
                    if m:
                        captcha_match = m
                        break
                        
        captcha_text = captcha_match.group(1) if captcha_match else "0 + 0"
        answer = "0"
        m2 = re.search(r'(\d+)\s*([\+\-\*])\s*(\d+)', captcha_text)
        if m2:
            a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
            if op == '+': answer = str(a + b)
            elif op == '-': answer = str(a - b)
            elif op == '*': answer = str(a * b)

        form = soup.find("form")
        if not form:
            p["login_status"] = "❌ No login form found"
            return False
            
        action = form.get("action")
        from urllib.parse import urljoin
        post_url = urljoin(login_url, action) if action else login_url

        form_data = {}
        for hidden in form.find_all("input", type="hidden"):
            name = hidden.get("name")
            if name: form_data[name] = hidden.get("value") or ""
        
        user_input = form.find("input", {"name": re.compile(r"user|email|id", re.I)}) or \
                     form.find("input", {"type": "text", "placeholder": re.compile(r"user|email", re.I)}) or \
                     form.find("input", {"type": "text"})
                     
        pass_input = form.find("input", {"name": re.compile(r"pass", re.I)}) or \
                     form.find("input", {"type": "password"})
                     
        captcha_input = form.find("input", {"placeholder": re.compile(r"answer|ans|code|verification|value|captcha", re.I)}) or \
                        form.find("input", {"name": re.compile(r"ans|captcha|ver|code", re.I)})
        
        user_field = user_input.get("name") if user_input else "username"
        pass_field = pass_input.get("name") if pass_input else "password"
        captcha_field = captcha_input.get("name") if captcha_input else "answer"

        form_data[user_field] = p.get("username", "")
        form_data[pass_field] = p.get("password", "")
        if captcha_field:
            form_data[captcha_field] = answer

        login_req = session.post(post_url, data=form_data, allow_redirects=True, timeout=15)
        
        msg_link = p.get("msg_link", "").strip()
        if not msg_link.startswith("http") and msg_link != "":
            msg_link = "http://" + msg_link
            
        check_url = msg_link if msg_link else f"{login_url.split('/login')[0]}/client/SMSCDRStats"
        
        check_res = session.get(check_url, timeout=10)
        
        if 'logout' in login_req.text.lower() or 'logout' in check_res.text.lower() or 'sms reports' in check_res.text.lower() or 'dashboard' in check_res.text.lower() or 'cdrs' in check_res.text.lower():
            panel_sessions[idx] = session
            p["login_status"] = "✅ Active & Fetching"
            return True
        else:
            p["login_status"] = f"❌ Login Failed (Math: {captcha_text} = {answer})"
            return False
            
    except Exception as e:
        p["login_status"] = f"❌ Error: {str(e)[:20]}"
        
    return False

def panel_monitor_thread():
    global processed_otps, recent_traffic, panel_sessions
    while True:
        try:
            for idx, p in enumerate(bot_settings.get("panels", [])):
                if p.get("status") == "ON":
                    
                    if p.get("type") == "Auto Captcha Panel":
                        sess = panel_sessions.get(idx)
                        
                        if not sess:
                            now = time.time()
                            if now - p.get("last_login_attempt", 0) < 30: 
                                continue 
                            p["last_login_attempt"] = now
                            
                            success = attempt_auto_login(p, idx)
                            save_db()
                            if not success:
                                continue 
                            sess = panel_sessions.get(idx)
                            
                        try:
                            msg_link = p.get("msg_link", "").strip()
                            if not msg_link:
                                login_url = p.get("login_url", "").strip()
                                if not login_url.startswith("http"):
                                    login_url = "http://" + login_url
                                msg_link = f"{login_url.split('/login')[0]}/client/SMSCDRStats"
                            parsed_data, res_text = fetch_cpt_panel_cdrs(p, sess, msg_link)
                            p["login_status"] = "✅ Active & Fetching"
                        except Exception as e:
                            p["login_status"] = "❌ Session Expired (Retrying...)"
                            del panel_sessions[idx]
                            save_db()
                            continue

                    elif p.get("api_url") or p.get("full_api_url"): 
                        full_url = p.get("full_api_url", "").strip()
                        url = p.get("api_url", "").strip()
                        token = p.get("token", "").strip()
                        if not full_url and not url: continue
                        
                        urls_to_try = panel_api_request_urls(p)
                        if not urls_to_try:
                            continue

                        parsed_data = []
                        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                        for try_url in urls_to_try:
                            try:
                                res = requests.get(try_url, headers=headers, timeout=10)
                                parsed_data = parse_panel_response(res.text, p)
                                if parsed_data:
                                    if not full_url and try_url != url and token:
                                        p["api_url"] = try_url.replace(token, "{token}")
                                        save_db()
                                    break
                            except: continue
                        if not parsed_data: continue
                    else:
                        continue
                    
                    if p.get("type") != "Auto Captcha Panel":
                        limit = p.get("records", 0)
                        if limit > 0: parsed_data = parsed_data[:limit]
                        
                    for item in parsed_data:
                        num = item["number"]
                        otp = item["otp"]
                        msg_text = item["message"]
                        unique_id = f"{num}_{otp}"
                        
                        if unique_id not in processed_otps:
                            processed_otps.add(unique_id)
                            if len(processed_otps) > 5000: processed_otps.clear()
                                 
                            char, iso = get_flag_and_code(num)
                            app_full_name, prem_app_html = get_service_info_html(p.get("name", "Panel"), msg_text)
                            current_time = time.time()
                            
                            recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                            recent_traffic.append({
                                "service": app_full_name,
                                "iso": iso,
                                "flag": char,
                                "number": num,
                                "time": current_time
                            })
                            save_local_db()
                                 
                            display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                            masked = mask_number(display_num)
                            lang = detect_language(msg_text)
                            
                            lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                            display_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {masked} | 💬 {lang_name}")
                            
                            for fw in bot_settings.get("fw_groups", []):
                                kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                                temp_row = []
                                styles = ["danger", "success", "primary"]
                                for i, btn in enumerate(fw.get("buttons", [])):
                                    b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                                    if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                                    temp_row.append(b_obj)
                                    if len(temp_row) == 2:
                                        kb.append(temp_row)
                                        temp_row = []
                                if temp_row: kb.append(temp_row)
                                send_message(fw["chat_id"], display_msg, reply_markup={"inline_keyboard": kb})
                            
                            owners = []
                            clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()
                            
                            for uid, session_data in user_active_sessions.items():
                                for act_num in session_data.get("nums", []):
                                    act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                    if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                        owners.append(uid)
                                        break
                                        
                            if not owners:
                                for stex_n, n_owner in stex_assigned_numbers.items():
                                    clean_stex = str(stex_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                    if clean_stex == clean_api_num or (len(clean_stex) >= 8 and clean_stex.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_stex[-8:])):
                                        owners.append(n_owner)
                                        
                            owners = list(set(owners)) 
                            for owner_id in owners:
                                lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                inbox_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {display_num} | 💬 {lang_name}")
                                inbox_kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": otp}, "style": "success"}]]
                                
                                reward = float(bot_settings.get("otp_reward", 0.0))
                                if reward > 0:
                                    update_balance(owner_id, reward)
                                    inbox_kb.append([{"text": f"Added {reward} tk", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                
                                send_message(owner_id, inbox_msg, reply_markup={"inline_keyboard": inbox_kb})
                                record_user_otp(owner_id, otp)
        except Exception as e:
            pass
        time.sleep(5) 

# ==========================================
# PostgreSQL User Management
# ==========================================
user_cache = {}

def get_user(user_id):
    if user_id in user_cache: return user_cache[user_id]
    if not db:
        user_key = str(user_id)
        data = local_users.get(user_key)
        if not data:
            data = {
                "user_id": user_id,
                "user_name": "",
                "username": "",
                "balance": 0.0,
                "otp": "",
                "total_refers": 0,
                "total_otps": 0,
                "banned": False,
                "verified": False,
                "language": None,
                "created_at": iso_now()
            }
            local_users[user_key] = data
            save_user_store()
        user_cache[user_id] = data
        return data
    
    doc_ref = db.collection('users').document(str(user_id))
    doc = doc_ref.get()
    if doc.exists: 
        data = doc.to_dict()
        if "total_otps" not in data: data["total_otps"] = 0
        if "total_refers" not in data: data["total_refers"] = 0
        if "balance" not in data: data["balance"] = 0.0
        if "user_name" not in data: data["user_name"] = ""
        if "username" not in data: data["username"] = ""
        if "otp" not in data: data["otp"] = ""
        if "banned" not in data: data["banned"] = False
        if "verified" not in data: data["verified"] = False
        if "language" not in data: data["language"] = None
        user_cache[user_id] = data
        return data
    else:
        new_user = {
            "user_id": user_id,
            "user_name": "",
            "username": "",
            "balance": 0.0,
            "otp": "",
            "total_refers": 0,
            "total_otps": 0,
            "banned": False,
            "verified": False,
            "language": None,
            "created_at": iso_now()
        }
        doc_ref.set(new_user)
        trigger_google_sheets_sync()
        user_cache[user_id] = new_user
        return new_user


def update_user_profile(user_id, user_name, username=None):
    """Save the user's display name and Telegram @username."""
    user_name = str(user_name or "").strip()[:120]
    normalized_username = (
        _normalize_username(username)[:120] if username is not None else None
    )
    if not user_name and normalized_username is None:
        return
    user = get_user(user_id)
    changed_fields = {}
    if user_name and user.get("user_name") != user_name:
        changed_fields["user_name"] = user_name
        user["user_name"] = user_name
    if normalized_username is not None and user.get("username", "") != normalized_username:
        changed_fields["username"] = normalized_username
        user["username"] = normalized_username
    if not changed_fields:
        return
    user["updated_at"] = iso_now()
    changed_fields["updated_at"] = user["updated_at"]
    try:
        if db:
            db.collection("users").document(str(user_id)).set(
                changed_fields,
                merge=True,
            )
            trigger_google_sheets_sync()
        else:
            local_users[str(user_id)] = user
            save_user_store()
    except Exception:
        pass


def record_user_otp(user_id, otp):
    """Save the latest OTP for the user and keep the existing OTP counter."""
    otp = str(otp or "").strip()[:32]
    if not otp:
        return
    user = get_user(user_id)
    user["otp"] = otp
    user["total_otps"] = int(user.get("total_otps", 0) or 0) + 1
    user["updated_at"] = iso_now()
    try:
        if db:
            db.collection("users").document(str(user_id)).set(
                {
                    "otp": otp,
                    "total_otps": postgres.Increment(1),
                    "updated_at": user["updated_at"],
                },
                merge=True,
            )
            trigger_google_sheets_sync()
        else:
            local_users[str(user_id)] = user
            save_user_store()
    except Exception:
        pass


def set_user_language(user_id, language):
    language = "BN" if str(language).upper() == "BN" else "EN"
    user = get_user(user_id)
    user["language"] = language
    if db:
        try:
            db.collection("users").document(str(user_id)).update({"language": language})
            trigger_google_sheets_sync()
        except Exception:
            pass
    else:
        local_users[str(user_id)] = user
        save_user_store()
    return language

COMMAND_ALIASES = {
    "নম্বর নিন": "GET NUMBER",
    "ট্রাফিক": "TRAFFIC",
    "২এফএ অনলাইন": "2FA ONLINE",
    "রেফার": "REFER",
    "উত্তোলন": "WITHDRAWAL",
    "সাপোর্ট": "SUPPORT",
    "ভাষা পরিবর্তন করুন": "CHANGE LANGUAGE",
    "বট রিস্টার্ট করুন": "RESTART BOT",
    "ভাষা": "CHANGE LANGUAGE",
    "অ্যাডমিন প্যানেল": "ADMIN PANEL",
}

def canonical_command(text):
    normalized = str(text or "").strip()
    return COMMAND_ALIASES.get(normalized, normalized.upper())

def update_balance(user_id, amount, reason="balance_adjustment"):
    amount = float(amount)
    user = get_user(user_id)
    new_balance = float(user.get("balance", 0.0)) + amount
    user["balance"] = new_balance
    user["updated_at"] = iso_now()
    try:
        if db:
            doc_ref = db.collection('users').document(str(user_id))
            doc_ref.set({
                "user_id": user_id,
                "balance": postgres.Increment(amount),
                "updated_at": iso_now()
            }, merge=True)
            trigger_google_sheets_sync()
        else:
            local_users[str(user_id)] = user
            save_user_store()
        record_history(
            user_id,
            reason,
            message=f"Balance changed by {amount:.2f} TK",
            amount=amount,
            balance_after=new_balance
        )
    except Exception:
        pass

def add_referral(inviter_id, new_user_id):
    if not db.collection('users').document(str(new_user_id)).get().exists:
        get_user(new_user_id) 
        reward = bot_settings.get("refer_reward", 0.2)
        update_balance(inviter_id, reward)
        db.collection('users').document(str(inviter_id)).update({"total_refers": postgres.Increment(1)})
        trigger_google_sheets_sync()
        if inviter_id in user_cache:
            user_cache[inviter_id]["total_refers"] = user_cache[inviter_id].get("total_refers", 0) + 1
        
        ref_msg = (
            f"{PEM['gift']} <b>New Referral !</b>\n"
            f"------------------\n"
            f"🔥 <b>You Received {reward} TK</b>\n"
            f"------------------\n"
            f"{PEM['user']} <b>From User ID:</b> <code>{new_user_id}</code>"
        )
        send_message(inviter_id, render_body_text(ref_msg))

# ==========================================
# UI Keyboards & Menu Builders
# ==========================================
def get_cancel_kb():
    return {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_state", "style": "danger"}]]}

def language_selector_markup():
    return {"inline_keyboard": [
        [{"text": "ENGLISH", "icon_custom_emoji_id": LANGUAGE_EMOJI_ID, "callback_data": "set_lang_EN", "style": "primary"}],
        [{"text": "BANGLA", "icon_custom_emoji_id": LANGUAGE_EMOJI_ID, "callback_data": "set_lang_BN", "style": "success"}],
    ]}

def send_language_selector(chat_id):
    text = "🌐 <b>SELECT LANGUAGE</b>\n\nCHOOSE YOUR LANGUAGE / আপনার ভাষা নির্বাচন করুন"
    send_message(chat_id, render_body_text(text), reply_markup=language_selector_markup())

def send_start_ui(chat_id):
    c_msg = bot_settings["custom_messages"].get("start", {})
    txt = render_body_text(c_msg.get("text", f"{PEM['hi']} Welcome!"))
    kb = []
    for button in c_msg.get("buttons", []):
        button_copy = button.copy()
        button_copy.setdefault("style", "primary")
        kb.append([button_copy])
    if kb:
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})
        send_message(chat_id, render_body_text(f"{PEM['gear']} NAVIGATION MENU:"), reply_markup=main_menu(chat_id))
    else:
        send_message(chat_id, txt, reply_markup=main_menu(chat_id))

def main_menu(user_id):
    kb = [
        [
            {"text": "GET NUMBER", "icon_custom_emoji_id": GET_NUMBER_EMOJI_ID, "style": "primary"}, 
            {"text": "TRAFFIC", "icon_custom_emoji_id": "5352877703043258544", "style": "success"}, 
        ],
        [
            {"text": "REFER", "icon_custom_emoji_id": "5420396762189831222", "style": "success"}, 
            {"text": "WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "style": "danger"}
        ]
    ]
    if is_admin(user_id):
        # Keep the admin-facing menu focused on admin tools.
        kb.append([{"text": "ADMIN PANEL", "icon_custom_emoji_id": "5420155432272438703", "style": "danger"}])
    else:
        kb.append([{"text": "SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "style": "primary"}])
    return {"keyboard": kb, "resize_keyboard": True}

def get_admin_text():
    users_count = len(all_known_users)
    total_files = len(number_batches)
    available_nums = sum(len(b["numbers"]) for b in number_batches.values())

    txt = f"""
{PEM['admin']} <b>ADMIN CONTROL PANEL</b> {PEM['admin']}
━━━━━━━━━━━━━━━━━━

{PEM['graph']} <b>DATABASE OVERVIEW</b>
— — — — — — — — — —
{PEM['user']} Users      » {users_count}
{PEM['file']} Files      » {total_files}
{PEM['num']} Numbers    » {total_uploaded_stats}
{PEM['ok']} Assigned   » {total_assigned_stats}
{PEM['rocket']} Available  » {available_nums}

{PEM['graph']} <b>STOCK LEVEL</b>
— — — — — — — — — —
[██████░░░░░░░░░] {available_nums} free
"""
    return render_body_text(txt)

def admin_panel_keyboard(admin_id=None):
    notification_status = "ON" if admin_id is None or get_join_notification_status(admin_id) else "OFF"
    return {"inline_keyboard": [
        [{"text": "LEADER BOARD SYSTEM", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "lb_main", "style": "success"}],
        [{"text": "Upload Number", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "upload_num", "style": "primary"},
         {"text": "Delete files", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "delete_files", "style": "danger"}],
        [{"text": "Broadcast", "icon_custom_emoji_id": "5789428375261023681", "callback_data": "broadcast_msg", "style": "success"},
         {"text": "System", "icon_custom_emoji_id": "5420155432272438703", "callback_data": "system_settings", "style": "primary"}],
        [{"text": f"User Join Notification: {notification_status}", "icon_custom_emoji_id": "5352980533150259581", "callback_data": "toggle_join_notify", "style": "success" if notification_status == "ON" else "danger"}],
        [{"text": "Download User Data", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "export_data", "style": "success"}],
        [{"text": "Backup All Data", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "backup_all_data", "style": "success"},
         {"text": "Restore All Data", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "restore_all_data", "style": "primary"}],
        [{"text": "Delete All Data", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "delete_all_data", "style": "danger"},
         {"text": "Google Sheets", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "google_sheet_status", "style": "primary"}],
        [{"text": "Used number", "icon_custom_emoji_id": "5352694861990501856", "callback_data": "show_used", "style": "success"},
         {"text": "Unused number", "icon_custom_emoji_id": "5352597830089347330", "callback_data": "show_unused", "style": "success"}],
        [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]
    ]}

def system_settings_keyboard():
    return {"inline_keyboard": [
        [{"text": "StexSMS Control", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "stex_control", "style": "success"},
         {"text": "Voltx Control", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "voltx_control", "style": "primary"}],
        [{"text": "Zenex Control", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "zenex_control", "style": "success"}],
        [{"text": "Force Join System", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "manage_fj", "style": "primary"},
         {"text": "Admin Management", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "manage_admins", "style": "danger"}],
        [{"text": "OTP Group", "icon_custom_emoji_id": "5190447043545438788", "callback_data": "manage_otp_groups", "style": "danger"},
         {"text": "User Management", "icon_custom_emoji_id": "5193063022226086560", "callback_data": "user_management", "style": "primary"}], 
         [{"text": "Panel MANAGEMENT", "icon_custom_emoji_id": "5336879280578138635", "callback_data": "manage_panels", "style": "danger"}],
        [{"text": "GX Control", "icon_custom_emoji_id": "5193100774988617665", "callback_data": "GX_control", "style": "primary"},
         {"text": "Premium Emoji", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "manage_emojis", "style": "success"}],
        [{"text": "Menu Design", "icon_custom_emoji_id": "5190751148704833975", "callback_data": "menu_design_list", "style": "primary"},
         {"text": "Test", "icon_custom_emoji_id": "5190781475468915802", "callback_data": "test_message_flow", "style": "primary"}], 
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
    ]}

def get_user_management_text():
    total = len(all_known_users)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    txt = f"""➖➖➖➖➖➖➖➖
《 👋 USER VIEW 》
➖➖➖➖➖➖➖➖
📊 LIVE STATISTICS:
➖➖➖➖➖➖➖➖
🫂 TOTAL USERS: {total}
✅ VERIFIED USERS: (Hidden to save DB Cost)
🚫 BANNED USERS: (Hidden to save DB Cost)
➖➖➖➖➖➖➖➖
⌛ UPDATED: {now_str}"""
    return render_body_text(txt)

def user_management_keyboard():
    return {"inline_keyboard": [
        [{"text": "Manage Balance", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "um_manage_balance", "style": "primary"},
         {"text": "Ban/Unban User", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "um_ban_unban", "style": "danger"}],
        [{"text": "User Profile", "icon_custom_emoji_id": "5352861489541714456", "callback_data": "um_user_profile", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def menu_design_list_keyboard():
    return {"inline_keyboard": [
        [{"text": "Edit /start Menu", "icon_custom_emoji_id": "5395444784611480792", "callback_data": "md_edit_start", "style": "primary"}],
        [{"text": "Edit GET NUMBER", "icon_custom_emoji_id": GET_NUMBER_EMOJI_ID, "callback_data": "md_edit_get_number", "style": "success"}],
        [{"text": "Edit Select Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "md_edit_select_country", "style": "primary"}],
        [{"text": "Edit TRAFFIC", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "md_edit_traffic", "style": "primary"},
         {"text": "Edit Refer", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "md_edit_refer", "style": "primary"}],
        [{"text": "Edit WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "callback_data": "md_edit_withdrawal", "style": "danger"},
         {"text": "Edit SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "md_edit_support", "style": "danger"}],
        [{"text": "Reset Defaults", "icon_custom_emoji_id": "5192812028632274956", "callback_data": "md_reset_defaults", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def menu_edit_options_keyboard(menu_key):
    return {"inline_keyboard": [
        [{"text": "Edit Body (Text)", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"md_text_{menu_key}", "style": "primary"}],
        [{"text": "Edit Inline Buttons", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"md_btns_{menu_key}", "style": "success"}],
        [{"text": "Back to Menus", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "menu_design_list", "style": "danger"}]
    ]}

def menu_buttons_list_keyboard(menu_key):
    kb = []
    btns = bot_settings["custom_messages"].get(menu_key, {}).get("buttons", [])
    for idx, btn in enumerate(btns):
        kb.append([{"text": f"Del: {btn['text']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"md_delbtn_{menu_key}_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Inline Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"md_addbtn_{menu_key}", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{menu_key}", "style": "primary"}])
    return {"inline_keyboard": kb}

def emoji_settings_keyboard():
    return {"inline_keyboard": [
        [{"text": "Upload Flags (TXT)", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "up_flags_txt", "style": "primary"},
         {"text": "Download Flags", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_flags_txt", "style": "success"}],
        [{"text": "Upload Services (TXT)", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "up_apps_txt", "style": "primary"},
         {"text": "Download Services", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_apps_txt", "style": "success"}],
        [{"text": "Delete All Flags", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "del_all_flags", "style": "danger"},
         {"text": "Add Single Emoji", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_single_emoji", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
    ]}

def fj_settings_keyboard():
    status_text = 'ON' if bot_settings['fj_on'] else 'OFF'
    status_icon = "5352694861990501856" if bot_settings['fj_on'] else "5318840353510408444"
    kb = [[{"text": f"STATUS: {status_text}", "icon_custom_emoji_id": status_icon, "callback_data": "toggle_fj", "style": "primary"}]]
    for idx, ch in enumerate(bot_settings["fj_channels"]):
        kb.append([{"text": f"Delete: {ch}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_fj_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Channel", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_fj", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}])
    return {"inline_keyboard": kb}

def admin_settings_keyboard():
    kb = []
    for idx, adm in enumerate(bot_settings["admins"]):
        text_btn = f"Owner: {adm}" if adm == OWNER_ID else f"Delete: {adm}"
        icon_id = "5353032893096567467" if adm == OWNER_ID else "5420130255174145507"
        cb_data = "ignore" if adm == OWNER_ID else f"del_adm_{idx}"
        kb.append([{"text": text_btn, "icon_custom_emoji_id": icon_id, "callback_data": cb_data, "style": "danger" if adm != OWNER_ID else "primary"}])
    kb.append([{"text": "Add Admin", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_adm", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}])
    return {"inline_keyboard": kb}

def otp_groups_list_keyboard():
    kb = [[{"text": "Edit OTP Button Link", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "edit_otp_link", "style": "primary"}]]
    for idx, fg in enumerate(bot_settings["fw_groups"]):
        kb.append([{"text": f"Group: {fg['chat_id']}", "icon_custom_emoji_id": "5193063022226086560", "callback_data": f"manage_fw_{idx}", "style": "primary"}])
    kb.append([{"text": "Add Forward Group", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_fw", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}])
    return {"inline_keyboard": kb}

def stex_control_keyboard():
    auto_status = "ON" if bot_settings.get("stex_auto", False) else "OFF"
    auto_emoji = "5352694861990501856" if auto_status == "ON" else "5420130255174145507"
    return {"inline_keyboard": [
        [{"text": "Add StexSMS Key", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_stex_key", "style": "success"},
         {"text": "View/Del Keys", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "view_stex_keys", "style": "danger"}],
        [{"text": "Manage StexSMS Services", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "manage_stex_srv", "style": "success"}],
        [{"text": f"Auto Range: {auto_status}", "icon_custom_emoji_id": auto_emoji, "callback_data": "toggle_stex_auto", "style": "primary"},
         {"text": "Search Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "stex_search_country", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def zenex_control_keyboard():
    auto_status = "ON" if bot_settings.get("zenex_auto", False) else "OFF"
    auto_emoji = "5352694861990501856" if auto_status == "ON" else "5420130255174145507"
    return {"inline_keyboard": [
        [{"text": "Add Zenex Key", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_zenex_key", "style": "success"},
         {"text": "View/Del Keys", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "view_zenex_keys", "style": "danger"}],
        [{"text": "Manage Zenex Services", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "manage_zenex_srv", "style": "success"}],
        [{"text": f"Auto Range: {auto_status}", "icon_custom_emoji_id": auto_emoji, "callback_data": "toggle_zenex_auto", "style": "primary"},
         {"text": "Search Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "zenex_search_country", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def voltx_control_keyboard():
    auto_status = "ON" if bot_settings.get("voltx_auto", False) else "OFF"
    auto_emoji = "5352694861990501856" if auto_status == "ON" else "5420130255174145507"
    return {"inline_keyboard": [
        [{"text": "Add Voltx Key", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_voltx_key", "style": "success"},
         {"text": "View/Del Keys", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "view_voltx_keys", "style": "danger"}],
        [{"text": "Manage Voltx Services", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "manage_voltx_srv", "style": "success"}],
        [{"text": f"Auto Range: {auto_status}", "icon_custom_emoji_id": auto_emoji, "callback_data": "toggle_voltx_auto", "style": "primary"},
         {"text": "Search Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "voltx_search_country", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def specific_fw_group_keyboard(idx):
    group = bot_settings["fw_groups"][idx]
    kb = []
    for b_idx, btn in enumerate(group.get("buttons", [])):
        kb.append([{"text": f"Del: {btn['text']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_fwbtn_{idx}_{b_idx}", "style": "danger"}])
    
    kb.append([{"text": "Add Inline Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"add_fwbtn_{idx}", "style": "success"}])
    kb.append([{"text": "Delete Entire Group", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"del_fw_{idx}", "style": "danger"}])
    kb.append([{"text": "Back to Groups", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "primary"}])
    return {"inline_keyboard": kb}

def GX_control_keyboard():
    w_status = "ON" if bot_settings["withdraw_on"] else "OFF"
    sup_status = "ON" if bot_settings.get("support_link") else "OFF"
    grp_status = "ON" if bot_settings.get("w_group") else "OFF"
    return {"inline_keyboard": [
        [{"text": f"WITHDRAW: {w_status}", "icon_custom_emoji_id": "5348469219761626211", "callback_data": "GX_toggle_w", "style": "primary"}],
        [{"text": f"MIN WITHDRAW: {bot_settings['min_withdraw']}", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "GX_min_w", "style": "success"},
         {"text": f"OTP REWARD: {bot_settings['otp_reward']}", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "GX_otp_r", "style": "primary"}],
        [{"text": f"REFER REWARD: {bot_settings['refer_reward']}", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "GX_ref_r", "style": "success"},
         {"text": f"COOLDOWN: {bot_settings['cooldown']}s", "icon_custom_emoji_id": "5337172996211648018", "callback_data": "GX_cool", "style": "primary"}],
        [{"text": f"NUM/REQ: {bot_settings['num_req']}", "icon_custom_emoji_id": "5337132498965010628", "callback_data": "GX_num_req", "style": "success"},
         {"text": f"NUM/SHARE: {bot_settings['num_share']}", "icon_custom_emoji_id": "5352862640592949843", "callback_data": "GX_num_share", "style": "primary"}],
        [{"text": f"SUPPORT LINK: {sup_status}", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "GX_sup_link", "style": "success"},
         {"text": "W. METHODS", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "manage_w_methods", "style": "primary"}],
        [{"text": f"W. GROUP: {grp_status}", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "GX_w_group", "style": "success"},
         {"text": "BACK", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
    ]}

def w_methods_keyboard():
    kb = []
    for idx, m in enumerate(bot_settings["w_methods"]):
        kb.append([{"text": f"Delete: {m}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_wm_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Method", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_wm", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "GX_control", "style": "primary"}])
    return {"inline_keyboard": kb}

def typed_panels_list_keyboard(p_type):
    kb = []
    for idx, p in enumerate(bot_settings["panels"]):
        if p.get("type", "API Panel") != p_type: continue
        action_text = f"Turn OFF {p['name']}" if p['status'] == 'ON' else f"Turn ON {p['name']}"
        action_icon = "5318840353510408444" if p['status'] == 'ON' else "5192812028632274956"
        icon_id = "5420155432272438703" 
        kb.append([
            {"text": action_text, "icon_custom_emoji_id": action_icon, "callback_data": f"tog_pnl_{idx}", "style": "danger" if p['status'] == 'ON' else "success"},
            {"text": f"{p['name']}", "icon_custom_emoji_id": icon_id, "callback_data": f"conf_pnl_{idx}", "style": "primary"}
        ])
    add_cb = "add_api_panel" if p_type == "API Panel" else "add_cpt_panel"
    kb.append([{"text": "Add New Provider", "icon_custom_emoji_id": "5420323438508155202", "callback_data": add_cb, "style": "success"}])
    kb.append([{"text": "Delete Provider", "icon_custom_emoji_id": "5336944168944047463", "callback_data": f"list_del_{'api' if p_type=='API Panel' else 'cpt'}", "style": "danger"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_panels", "style": "primary"}])
    return {"inline_keyboard": kb}

def panel_config_keyboard(idx):
    p = bot_settings["panels"][idx]
    
    kb = []
    action_text = "Turn OFF" if p['status'] == 'ON' else "Turn ON"
    action_icon = "5318840353510408444" if p['status'] == 'ON' else "5192812028632274956"
    kb.append([{"text": action_text, "icon_custom_emoji_id": action_icon, "callback_data": f"tog_pnl_{idx}", "style": "danger" if p['status'] == 'ON' else "success"}])
    
    if p["type"] != "Auto Captcha Panel":
        rec_count_text = "All (Unlimited)" if p.get('records', 0) == 0 else str(p.get('records'))
        kb.append([{"text": "Set API URL", "icon_custom_emoji_id": "5420517437885943844", "callback_data": f"set_p_api_{idx}", "style": "primary"}])
        kb.append([{"text": "Set Token", "icon_custom_emoji_id": "5353022963132174959", "callback_data": f"set_p_tok_{idx}", "style": "primary"}])
        kb.append([{"text": "🌐 Full API (URL+Token)", "icon_custom_emoji_id": "5420517437885943844", "callback_data": f"set_p_fapi_{idx}", "style": "primary"}])
        kb.append([{"text": f"Set Records Count: {rec_count_text}", "icon_custom_emoji_id": "5192739271886282680", "callback_data": f"set_p_rec_{idx}", "style": "primary"}])
        
    kb.append([{"text": "Test Connection", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"test_p_conn_{idx}", "style": "success"}])
        
    back_data = "manage_api_panels" if p.get("type", "API Panel") == "API Panel" else "manage_cpt_panels"
    kb.append([{"text": "Back to Providers", "icon_custom_emoji_id": "5267490665117275176", "callback_data": back_data, "style": "danger"}])
    return {"inline_keyboard": kb}

def build_traffic_ui():
    global recent_traffic
    current_time = time.time()
    recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 600]
    
    stats = {}
    for t in recent_traffic:
        srv = t.get("service", "Unknown")
        iso = t.get("iso", "XX")
        flag = t.get("flag", "🌍")
        
        if srv not in stats:
            stats[srv] = {}
        if iso not in stats[srv]:
            stats[srv][iso] = {"count": 0, "flag": flag}
        stats[srv][iso]["count"] += 1
        
    txt = "🔥 10 Minute LIVE Traffic\n\n"
    
    kb = []
    if not stats:
        txt += "<i>No recent traffic found in the last 10 minutes...</i>\n"
    else:
        srv_totals = []
        for srv, countries in stats.items():
            total = sum(c["count"] for c in countries.values())
            srv_totals.append((srv, total, countries))
        
        srv_totals.sort(key=lambda x: x[1], reverse=True)
        
        for srv, total, countries in srv_totals:
            app_full_name, prem_app_html = get_service_info_html(srv)
            txt += f"{prem_app_html} {app_full_name.upper()} {total}\n"
            
            c_list = sorted(countries.items(), key=lambda x: x[1]["count"], reverse=True)
            c_list = c_list[:7]
            
            for i, (iso, c_data) in enumerate(c_list):
                prem_flag_html = get_flag_info_html(iso)
                count = c_data["count"]
                
                c_name = iso
                for code, fdata in bot_settings.get("premium_flags", {}).items():
                    if fdata.get("iso") == iso:
                        c_name = fdata.get("name", iso)
                        break
                
                if count < 20:
                    status_text = "LOW"
                    status_emoji = '<tg-emoji emoji-id="5408846744727334338">🔴</tg-emoji>'
                elif count < 30:
                    status_text = "MEDIUM"
                    status_emoji = '<tg-emoji emoji-id="5409220909393290791">🟡</tg-emoji>'
                else:
                    status_text = "HIGH"
                    status_emoji = '<tg-emoji emoji-id="5192812028632274956">🟢</tg-emoji>'
                        
                txt += f"{prem_flag_html} {c_name.upper()} :  {status_text} {status_emoji}\n"
                
            txt += "\n"
        
        now = datetime.now()
        current_time_str = now.strftime("%I:%M %p")
        updated_emoji = '<tg-emoji emoji-id="5336983442125001376">🕒</tg-emoji>'
        txt += f"{updated_emoji} Updated {current_time_str}\n"

        for srv, _, _ in srv_totals: 
            safe_srv = srv[:20] 
            app_full_name, _ = get_service_info_html(safe_srv, safe_srv)
            app_icon_id = get_service_icon_id(safe_srv, safe_srv)
            kb.append([{"text": f"Explore {app_full_name} Range", "icon_custom_emoji_id": app_icon_id, "callback_data": f"exp_rng_{safe_srv}", "style": "success"}])
            
    txt = render_body_text(txt)
    kb.append([{"text": "Refresh", "icon_custom_emoji_id": "5465368548702446780", "callback_data": "refresh_traffic", "style": "primary"}])
    kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
    
    return txt, {"inline_keyboard": kb}

# ==========================================
# OPTIMIZED NUMBER FETCHING FUNCTIONS
# ==========================================

def requested_number_count():
    """Return a safe, bounded number count from the admin setting."""
    try:
        # The admin value is the hard upper limit for one request.  Keep a
        # generous safety ceiling to prevent an accidental huge API fan-out,
        # while never returning more than this configured value.
        return max(1, min(50, int(bot_settings.get("num_req", 1))))
    except (TypeError, ValueError):
        return 1


def fetch_stex_number(api_key, query):
    try:
        headers = {"mauthapi": api_key}
        res = requests.post(f"{STEX_BASE_URL}/getnum", json={"rid": query}, headers=headers, timeout=5)
        data = res.json()
        if data.get("meta", {}).get("code") == 200 and data.get("data"):
            num_str = str(data["data"].get("no_plus_number", "")).replace("+", "")
            if not num_str:
                num_str = str(data["data"].get("national_number", "")).replace("+", "")
            if num_str:
                return num_str
    except:
        pass
    return None

def fetch_voltx_number(api_key, query):
    try:
        headers = {"mauthapi": api_key}
        res = requests.post(f"{VOLTX_BASE_URL}/getnum", json={"rid": query}, headers=headers, timeout=5)
        data = res.json()
        if data.get("meta", {}).get("code") == 200 and data.get("data"):
            num_str = str(data["data"].get("no_plus_number", "")).replace("+", "")
            if not num_str:
                num_str = str(data["data"].get("national_number", "")).replace("+", "")
            if num_str:
                return num_str
    except:
        pass
    return None

def fetch_zenex_number(api_key, query):
    try:
        headers = {"mapikey": api_key}
        res = requests.post(f"{ZENEX_BASE_URL}/v1/getnum", json={"range": query, "is_national": False, "remove_plus": False}, headers=headers, timeout=5)
        data = res.json()
        if data.get("meta", {}).get("code") == 200 and data.get("data"):
            num_str = str(data["data"].get("full_number", "")).replace("+", "")
            if not num_str:
                num_str = str(data["data"].get("number", "")).replace("+", "")
            if num_str:
                return num_str
    except:
        pass
    return None

def _canonical_number(value):
    """Normalize provider/local values for duplicate and ownership checks."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if 7 <= len(digits) <= 18 else ""


def _number_is_claimed(value):
    canonical = _canonical_number(value)
    if not canonical:
        return True
    with number_allocation_lock:
        return canonical in claimed_numbers


def _claim_provider_number(source, number, owner_id):
    """Atomically claim a real provider number exactly once in this process."""
    canonical = _canonical_number(number)
    if not canonical:
        return None
    with number_allocation_lock:
        if canonical in claimed_numbers:
            return None
        claimed_numbers.add(canonical)
        if source == "stex":
            stex_assigned_numbers[canonical] = owner_id
        elif source == "voltx":
            voltx_assigned_numbers[canonical] = owner_id
        else:
            zenex_assigned_numbers[canonical] = owner_id
    return canonical


def _reserve_local_numbers(query, chat_id, req_count, service=None, country=None):
    """Reserve local stock fairly: one number per batch before a second one.

    A batch is the local equivalent of a provider/panel.  This prevents one
    uploaded panel/file from consuming the complete request while other
    configured sources are never used.
    """
    global total_assigned_stats
    query_digits = re.sub(r"\D", "", str(query or ""))
    try:
        limit = max(1, int(req_count))
    except (TypeError, ValueError):
        limit = 1

    selected = []
    with number_allocation_lock:
        candidates = {}
        for batch_id, batch in number_batches.items():
            if service is not None and str(batch.get("service", "")) != str(service):
                continue
            if country is not None and str(batch.get("country", "")) != str(country):
                continue
            rows = []
            for index, item in enumerate(batch.get("numbers", [])):
                if not isinstance(item, dict):
                    continue
                raw = item.get("num", "")
                canonical = _canonical_number(raw)
                if not canonical or (query_digits and not canonical.startswith(query_digits)):
                    continue
                if chat_id is not None and chat_id in item.get("used_by", []):
                    continue
                if canonical in claimed_numbers:
                    continue
                rows.append((index, item, canonical))
            if rows:
                # Keep file order stable; fairness, not randomness, is the
                # important part here and makes debugging allocations possible.
                candidates[batch_id] = rows

        # Round-robin across batches.  If only two panels have stock and the
        # admin requested three numbers, the third comes from the first
        # panel that still has a real available number.
        while candidates and len(selected) < limit:
            progressed = False
            for batch_id in list(candidates):
                rows = candidates.get(batch_id, [])
                if not rows:
                    candidates.pop(batch_id, None)
                    continue
                _index, item, canonical = rows.pop(0)
                if canonical in claimed_numbers:
                    continue
                claimed_numbers.add(canonical)
                if chat_id is not None:
                    used_by = item.setdefault("used_by", [])
                    if chat_id not in used_by:
                        used_by.append(chat_id)
                item["shares"] = int(item.get("shares", 0) or 0) + 1
                item["to_remove"] = True  # one number belongs to one user
                used_numbers_list.append(item.get("num", canonical))
                assigned_number_rates[item.get("num", canonical)] = float(
                    number_batches[batch_id].get(
                        "rate", bot_settings.get("otp_reward", 0.0)
                    )
                )
                selected.append(item.get("num", canonical))
                total_assigned_stats += 1
                progressed = True
                if len(selected) >= limit:
                    break
            if not progressed:
                break

        for batch_id in list(number_batches):
            number_batches[batch_id]["numbers"] = [
                item for item in number_batches[batch_id].get("numbers", [])
                if not item.get("to_remove")
            ]

    if selected:
        save_db()
    return selected


def fetch_numbers_fast(query, chat_id=None, req_count=1, source_hint=None):
    """Fetch no more than the admin request count using fair source rotation.

    First round: one real number from every eligible provider/panel.
    Remaining slots: use the provider that has produced the best real result
    so far, falling back to the next provider when it is empty.  A number is
    atomically claimed before it is returned, so concurrent users cannot see
    the same number.
    """
    try:
        req_count = max(1, min(50, int(req_count)))
    except (TypeError, ValueError):
        req_count = 1

    fetched_nums = _reserve_local_numbers(query, chat_id, req_count)
    if len(fetched_nums) >= req_count:
        return fetched_nums[:req_count], "local"

    stex_allowed = bot_settings.get("search_countries", [])
    voltx_allowed = bot_settings.get("voltx_search_countries", [])
    zenex_allowed = bot_settings.get("zenex_search_countries", [])
    is_stex_allowed = any(str(query).startswith(str(c)) for c in stex_allowed) if stex_allowed else False
    is_voltx_allowed = any(str(query).startswith(str(c)) for c in voltx_allowed) if voltx_allowed else False
    is_zenex_allowed = any(str(query).startswith(str(c)) for c in zenex_allowed) if zenex_allowed else False

    provider_defs = {
        "stex": (is_stex_allowed, bot_settings.get("stex_keys", []), fetch_stex_number),
        "voltx": (is_voltx_allowed, bot_settings.get("voltx_keys", []), fetch_voltx_number),
        "zenex": (is_zenex_allowed, bot_settings.get("zenex_keys", []), fetch_zenex_number),
    }
    if source_hint in provider_defs:
        provider_defs = {
            source_hint: provider_defs[source_hint]
        }

    groups = {}
    for source, (allowed, keys, fetcher) in provider_defs.items():
        if allowed:
            usable_keys = [str(key).strip() for key in list(keys)[:2] if str(key).strip()]
            if usable_keys:
                groups[source] = {
                    "keys": usable_keys,
                    "fetcher": fetcher,
                    "cursor": 0,
                    "successes": 0,
                    "attempts": 0,
                }

    def call_source(source):
        group = groups[source]
        key = group["keys"][group["cursor"] % len(group["keys"])]
        group["cursor"] += 1
        group["attempts"] += 1
        try:
            return group["fetcher"](key, query)
        except Exception:
            return None

    def accept(source, number):
        claimed = _claim_provider_number(source, number, chat_id)
        if not claimed or claimed in {_canonical_number(item) for item in fetched_nums}:
            return False
        fetched_nums.append(claimed)
        groups[source]["successes"] += 1
        return True

    # Every active source gets one chance in the first round.  This is the
    # piece that was missing when three auto ranges were enabled.
    source_order = list(groups)
    if source_order:
        with ThreadPoolExecutor(max_workers=len(source_order)) as executor:
            futures = {
                source: executor.submit(call_source, source)
                for source in source_order
            }
            for source in source_order:
                try:
                    accept(source, futures[source].result(timeout=7))
                except Exception:
                    continue

    # Fill only the remaining requested slots.  Prefer sources that already
    # returned a real number; ties retain admin/provider order.
    attempts = 0
    max_attempts = max(1, req_count * max(2, len(groups)))
    while groups and len(fetched_nums) < req_count and attempts < max_attempts:
        ranked = sorted(
            groups,
            key=lambda source: (
                -groups[source]["successes"],
                groups[source]["attempts"],
                source_order.index(source),
            ),
        )
        got_one = False
        for source in ranked:
            if len(fetched_nums) >= req_count or attempts >= max_attempts:
                break
            attempts += 1
            if accept(source, call_source(source)):
                got_one = True
                break
        if not got_one and attempts >= max_attempts:
            break

    if fetched_nums:
        save_db()
        return fetched_nums[:req_count], "api"
    return [], None

# ==========================================
# Message Handler
# ==========================================
def handle_message(msg):
    global total_uploaded_stats
    chat_id = msg["chat"]["id"]
    chat_type = msg["chat"].get("type", "private")
    
    if chat_type != "private":
        return
        
    text = normal_button_text(msg.get("text", ""))
    command = canonical_command(text)
    from_user = msg.get("from", {})
    full_name = " ".join(
        part for part in (
            from_user.get("first_name", ""),
            from_user.get("last_name", ""),
        ) if part
    ).strip()
    if not full_name:
        full_name = from_user.get("username", "") or str(chat_id)
    update_user_profile(chat_id, full_name, from_user.get("username", ""))
    is_new_user = register_user_local(chat_id)
    if is_new_user:
        notify_admins_new_user(msg, chat_id)

    if is_user_banned(chat_id):
        send_message(chat_id, render_body_text("🚫 <b>You are banned from using this bot!</b>\nIf you think this is a mistake, please contact support."))
        return
    
    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1 and parts[1].isdigit():
            inviter = int(parts[1])
            if inviter != chat_id:
                if db:
                    doc = db.collection('users').document(str(chat_id)).get()
                    if not doc.exists:
                        get_user(chat_id)
                        db.collection('users').document(str(chat_id)).update({"referred_by": inviter, "ref_paid": False})
                        
    # Users without a saved language use English by default; existing
    # language preferences continue to be respected by the localization layer.

    # Restart only resets temporary UI flow. Persistent users, settings,
    # balances, uploaded numbers and admin data remain untouched.
    if command == "RESTART BOT":
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        user_cooldowns.pop(chat_id, None)
        expire_previous_number(chat_id)
        send_start_ui(chat_id)
        return

    if not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return
        
    MAIN_MENU_CMDS = ["GET NUMBER", "TRAFFIC", "REFER", "WITHDRAWAL", "SUPPORT", "CHANGE LANGUAGE", "RESTART BOT", "ADMIN PANEL", "2FA ONLINE"]
    
    is_main_cmd = False
    if command in MAIN_MENU_CMDS or text.startswith("/start"):
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        is_main_cmd = True

    if command == "CHANGE LANGUAGE":
        send_language_selector(chat_id)
        return
    
    if chat_id in user_states and not is_main_cmd:
        state = user_states[chat_id]

        if state == "wait_for_restore_json":
            if "document" not in msg:
                send_message(
                    chat_id,
                    render_body_text("📥 Please upload an .xlsx, .json or .csv backup file."),
                    reply_markup=get_cancel_kb(),
                )
                return
            document = msg["document"]
            filename = document.get("file_name", "backup.json")
            extension = os.path.splitext(filename.lower())[1]
            if extension not in (".json", ".xlsx", ".csv"):
                send_message(
                    chat_id,
                    render_body_text("❌ Only .xlsx, .json or .csv files are accepted."),
                    reply_markup=get_cancel_kb(),
                )
                return
            try:
                file_info = requests.get(
                    f"{BASE_URL}/getFile",
                    params={"file_id": document["file_id"]},
                    timeout=20,
                ).json()
                file_path = file_info.get("result", {}).get("file_path")
                if not file_path:
                    raise ValueError("Telegram did not return a file path.")
                raw_backup = requests.get(f"{FILE_URL}{file_path}", timeout=30).content
                if extension == ".json":
                    backup = json.loads(raw_backup.decode("utf-8"))
                elif extension == ".xlsx":
                    backup = xlsx_to_backup(raw_backup)
                else:
                    backup = csv_to_backup(raw_backup)
                if not isinstance(backup, dict) or not isinstance(
                    backup.get("collections"), dict
                ):
                    raise ValueError("This does not look like a valid bot backup.")
                temp_data.setdefault(chat_id, {})["restore_backup"] = backup
                temp_data[chat_id]["restore_is_full"] = isinstance(
                    backup.get("runtime"), dict
                )
                user_states[chat_id] = "wait_for_restore_confirm"
                restore_msg_id = temp_data[chat_id].get("msg_id")
                if temp_data[chat_id]["restore_is_full"]:
                    restore_scope = (
                        "The uploaded full JSON will be added to the current Users, "
                        "Withdrawals, History, number stock, settings and provider "
                        "configuration. Duplicate records will be kept only once."
                    )
                else:
                    restore_scope = (
                        "This is a sheet/legacy backup. Its Users, Withdrawals and "
                        "History records will be added, with duplicate IDs merged."
                    )
                confirmation = (
                    "⚠️ <b>CONFIRM DATA MERGE</b>\n\n"
                    f"{restore_scope}\nCurrent data will not be deleted.\n\n"
                    "Continue?"
                )
                edit_message(
                    chat_id,
                    restore_msg_id,
                    render_body_text(confirmation),
                    reply_markup={"inline_keyboard": [
                        [{"text": "YES, RESTORE", "icon_custom_emoji_id": "5352694861990501856",
                          "callback_data": "restore_confirm", "style": "danger"}],
                        [{"text": "NO, CANCEL", "icon_custom_emoji_id": "5420130255174145507",
                          "callback_data": "restore_cancel", "style": "primary"}],
                    ]},
                )
            except Exception as exc:
                send_message(
                    chat_id,
                    render_body_text(f"❌ Backup could not be read: <code>{html.escape(str(exc))}</code>"),
                    reply_markup=get_cancel_kb(),
                )
            return

        elif state == "wait_for_restore_confirm":
            send_message(chat_id, render_body_text("Use the confirmation buttons above or press Cancel."))
            return

        elif state == "wait_for_cpanel_url" and text:
            temp_data[chat_id]["p_data"]["login_url"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_user"
            send_message(chat_id, render_body_text("2️⃣ <b>Username</b>\n➡️ Panel এর Username দিন:"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_user" and text:
            temp_data[chat_id]["p_data"]["username"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_pass"
            send_message(chat_id, render_body_text("3️⃣ <b>Password</b>\n➡️ Panel এর Password দিন:"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_pass" and text:
            temp_data[chat_id]["p_data"]["password"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_msg_link"
            send_message(chat_id, render_body_text("4️⃣ <b>Message Link</b>\n➡️ যেখান থেকে SMS/OTP ডাটা (JSON) আসবে সেই Link দিন:"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_msg_link" and text:
            temp_data[chat_id]["p_data"]["msg_link"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_num_col_name"
            send_message(chat_id, render_body_text("5️⃣ <b>Number Column Name</b>\n➡️ Data তে Number column এর নাম কী? (যেমন: number, phone):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_num_col_name" and text:
            temp_data[chat_id]["p_data"]["num_col_name"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_num_col_idx"
            send_message(chat_id, render_body_text("6️⃣ <b>Number Column Serial</b>\n➡️ Number Column এর Serial Number কত? (যেমন: 3, 5):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_num_col_idx" and text:
            if text.isdigit():
                temp_data[chat_id]["p_data"]["num_col_idx"] = int(text)
                user_states[chat_id] = "wait_for_cpanel_msg_col_name"
                send_message(chat_id, render_body_text("7️⃣ <b>Message Column Name</b>\n➡️ Message/OTP column এর নাম কী? (যেমন: message, sms):"), reply_markup=get_cancel_kb())
            else:
                 send_message(chat_id, render_body_text("❌ Please enter a valid number serial!"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_msg_col_name" and text:
            temp_data[chat_id]["p_data"]["msg_col_name"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_msg_col_idx"
            send_message(chat_id, render_body_text("8️⃣ <b>Message Column Serial</b>\n➡️ Message Column এর Serial Number কত? (যেমন: 5, 7):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_cpanel_msg_col_idx" and text:
            if text.isdigit():
                temp_data[chat_id]["p_data"]["msg_col_idx"] = int(text)
                temp_data[chat_id]["p_data"]["login_status"] = "⏳ Pending Auto-Login..."
                
                bot_settings["panels"].append(temp_data[chat_id]["p_data"])
                save_db()
                
                send_message(chat_id, render_body_text(f"{PEM['ok']} <b>Auto Captcha Panel Added Successfully!</b>\nবট এখন থেকে নিজেই ব্যাকগ্রাউন্ডে ক্যাপচা সলভ করে লগিন করে নিবে।"), reply_markup=main_menu(chat_id))
                
                msg_id = temp_data[chat_id]["msg_id"]
                handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_cpt_panels", "id": "internal"})
                
                del user_states[chat_id]
                del temp_data[chat_id]
            else:
                 send_message(chat_id, render_body_text("❌ Please enter a valid number serial!"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_bal_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID! Please send a numeric User ID."), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc = db.collection('users').document(str(target_uid)).get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                current_bal = doc.to_dict().get('balance', 0.0)
                temp_data[chat_id]["target_uid"] = target_uid
                user_states[chat_id] = "wait_for_um_bal_amt"
                send_message(chat_id, render_body_text(f"✅ User found!\n💰 Current Balance: {current_bal} ৳\n\n📝 Send the amount to ADD (e.g. 50) or REMOVE (e.g. -50):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_bal_amt" and text:
            try:
                amt = float(text.strip())
                target_uid = temp_data[chat_id]["target_uid"]
                update_balance(target_uid, amt)
                send_message(chat_id, render_body_text(f"{PEM['ok']} Balance updated successfully for {target_uid}!"), reply_markup=main_menu(chat_id))
                send_message(target_uid, render_body_text(f"🔔 Your balance has been adjusted by <b>{amt} ৳</b> by an Admin."))
                del user_states[chat_id]
                del temp_data[chat_id]
            except ValueError:
                send_message(chat_id, render_body_text("❌ Invalid amount! Please send a number."), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_ban_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID!"), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc_ref = db.collection('users').document(str(target_uid))
                doc = doc_ref.get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                current_status = doc.to_dict().get("banned", False)
                new_status = not current_status
                doc_ref.update({"banned": new_status})
                
                user_banned_cache[target_uid] = {'banned': new_status, 'time': time.time()}
                
                status_text = "BANNED 🚫" if new_status else "UNBANNED ✅"
                send_message(chat_id, render_body_text(f"✅ User {target_uid} has been {status_text}!"), reply_markup=main_menu(chat_id))
                del user_states[chat_id]
                del temp_data[chat_id]
            return

        elif state == "wait_for_um_prof_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID!"), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc = db.collection('users').document(str(target_uid)).get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                data = doc.to_dict()
                is_verified = True if data.get('total_otps', 0) > 0 else data.get('verified', False)
                prof_text = f"""➖➖➖➖➖➖➖➖
👤 <b>USER PROFILE</b>
➖➖➖➖➖➖➖➖
🆔 ID: <code>{target_uid}</code>
💰 Balance: {data.get('balance', 0.0)} ৳
🤝 Total Refers: {data.get('total_refers', 0)}
🔐 Total OTPs: {data.get('total_otps', 0)}
✅ Verified: {is_verified}
🚫 Banned: {data.get('banned', False)}
➖➖➖➖➖➖➖➖"""
                kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "user_management", "style": "primary"}]]}
                send_message(chat_id, render_body_text(prof_text), reply_markup=kb)
                del user_states[chat_id]
                del temp_data[chat_id]
            return

        elif state == "wait_for_menu_text" and text:
            try:
                menu_key = temp_data[chat_id]["menu_key"]
                formatted_html_text = extract_premium_html(msg)
                
                bot_settings["custom_messages"][menu_key]["text"] = formatted_html_text
                save_db()
                
                delete_message(chat_id, msg["message_id"])
                
                preview_text = render_body_text(formatted_html_text)
                success_text = f"{PEM['ok']} <b>Message Body Updated successfully!</b>\n\n🎨 <b>Editing: {menu_key.upper()}</b>\n\nPreview of current Text:\n{preview_text}"
                edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(success_text), reply_markup=menu_edit_options_keyboard(menu_key))
            except Exception as e:
                send_message(chat_id, f"❌ Error saving text: {e}")
            finally:
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
            return
            
        elif state == "wait_for_menu_btn" and text:
            try:
                menu_key = temp_data[chat_id]["menu_key"]
                if "-" in text:
                    parts = text.split("-", 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    
                    emoji_id = None
                    emoji_char = ""
                    for ent in msg.get("entities", []):
                        if ent.get("type") == "custom_emoji":
                            emoji_id = ent.get("custom_emoji_id")
                            offset = ent.get("offset", 0)
                            length = ent.get("length", 0)
                            b_text = text.encode('utf-16-le')
                            emoji_char = b_text[offset*2:(offset+length)*2].decode('utf-16-le')
                            break
                            
                    if emoji_char:
                        btn_text = btn_text.replace(emoji_char, "").strip()
                        
                    btn_data = {"text": btn_text, "url": btn_url, "style": "primary"}
                    if emoji_id:
                        btn_data["icon_custom_emoji_id"] = emoji_id
                        
                    bot_settings["custom_messages"][menu_key]["buttons"].append(btn_data)
                    save_db()
                    delete_message(chat_id, msg["message_id"])
                    edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"{PEM['gear']} <b>Edit Inline Buttons: {menu_key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(menu_key))
                else:
                    send_message(chat_id, render_body_text(f"{PEM['no']} Invalid format. Use <code>Button Text - https://link.com</code>"))
            except Exception as e:
                 pass
            finally:
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
            return

        elif state == "wait_for_test_service" and text:
            temp_data[chat_id]["service"] = text.strip()
            user_states[chat_id] = "wait_for_test_number"
            send_message(chat_id, render_body_text("📝 Send the Number (e.g. +8801712345678):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_test_number" and text:
            temp_data[chat_id]["number"] = text.strip()
            user_states[chat_id] = "wait_for_test_otp"
            send_message(chat_id, render_body_text("📝 Send the OTP (e.g. 556677):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_test_otp" and text:
            temp_data[chat_id]["otp"] = text.strip()
            user_states[chat_id] = "wait_for_test_lang"
            send_message(chat_id, render_body_text("📝 Send the Language (e.g. EN, AR):"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_test_lang" and text:
            lang = text.strip().upper()
            if not lang.startswith("#"):
                lang = "#" + lang
                
            srv = temp_data[chat_id]["service"]
            num = temp_data[chat_id]["number"]
            otp = temp_data[chat_id]["otp"]
            
            masked = mask_number(num)
            prem_flag_html = get_flag_info_html(num)
            char, iso = get_flag_and_code(num)
            app_full_name, prem_app_html = get_service_info_html(srv)
            
            lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
            msg_text = render_body_text(f"{prem_flag_html} {iso} | {prem_app_html} {masked} | 💬 {lang_name}")
            
            for fw in bot_settings.get("fw_groups", []):
                kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                temp_row = []
                styles = ["danger", "success", "primary"]
                for i, btn in enumerate(fw.get("buttons", [])):
                    b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                    if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                    temp_row.append(b_obj)
                    if len(temp_row) == 2:
                        kb.append(temp_row)
                        temp_row = []
                if temp_row: kb.append(temp_row)
                send_message(fw["chat_id"], msg_text, reply_markup={"inline_keyboard": kb})
                
            send_message(chat_id, render_body_text(f"{PEM['ok']} Test message formatted and sent to all Forward Groups!"), reply_markup=main_menu(chat_id))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_emoji_extract":
            entities = msg.get("entities", [])
            custom_emoji_id = None
            emoji_text = ""
            for ent in entities:
                if ent.get("type") == "custom_emoji":
                    custom_emoji_id = ent.get("custom_emoji_id")
                    offset = ent.get("offset", 0)
                    length = ent.get("length", 0)
                    b_text = msg.get("text", "").encode('utf-16-le')
                    emoji_text = b_text[offset*2:(offset+length)*2].decode('utf-16-le')
                    break
            
            if custom_emoji_id:
                temp_data[chat_id] = {"id": custom_emoji_id, "char": emoji_text}
                user_states[chat_id] = "wait_for_emoji_details"
                send_message(chat_id, render_body_text(f"{PEM['ok']} Emoji ID পাওয়া গেছে: <code>{custom_emoji_id}</code>\n\n📌 এখন এটি সেভ করার জন্য টাইপ এবং নাম লিখুন।\n\n<b>ফরমেট:</b>\n`FLAG | 880 | BD | Bangladesh`\nঅথবা\n`APP | WhatsApp`"), reply_markup=get_cancel_kb())
            else:
                send_message(chat_id, render_body_text(f"{PEM['no']} কোনো Premium Emoji পাওয়া যায়নি! দয়া করে Custom Emoji সেন্ড করুন।"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_emoji_details" and text:
            parts = [p.strip() for p in text.split("|")]
            mode = parts[0].upper()
            eid = temp_data[chat_id]["id"]
            char = temp_data[chat_id]["char"]
            
            if mode == "FLAG" and len(parts) == 4:
                code, iso, name = parts[1], parts[2], parts[3]
                bot_settings["premium_flags"][code] = {"char": char, "iso": iso.upper(), "name": name, "id": eid}
                save_db()
                send_message(chat_id, render_body_text(f"{PEM['ok']} Flag Emoji সেভ হয়েছে!\nCode: {code} | Name: {name}"), reply_markup=emoji_settings_keyboard())
            elif mode == "APP" and len(parts) == 2:
                name = parts[1]
                bot_settings["premium_apps"][name.upper()] = {"char": char, "id": eid, "name": name.title()}
                save_db()
                send_message(chat_id, render_body_text(f"{PEM['ok']} App Emoji সেভ হয়েছে!\nName: {name}"), reply_markup=emoji_settings_keyboard())
            else:
                send_message(chat_id, render_body_text(f"{PEM['no']} ফরম্যাট ভুল!\n\nসঠিক ফরম্যাট:\n`FLAG | 880 | BD | Bangladesh`\n`APP | WhatsApp`"))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state in ["wait_for_flag_txt", "wait_for_app_txt"] and "document" in msg:
            doc = msg["document"]
            if not doc["file_name"].endswith(".txt"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Please upload a .txt file only."))
                return
            file_id = doc["file_id"]
            file_info = requests.get(f"{BASE_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            content = requests.get(f"{FILE_URL}{file_path}").text
            
            mode = "flags" if state == "wait_for_flag_txt" else "apps"
            count = 0
            
            if mode == "flags":
                for line in content.splitlines():
                    json_match = re.search(r'(\{.*\})', line)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            char = data.get("emoji")
                            eid = data.get("id")
                            
                            prefix_str = line[:json_match.start()].strip()
                            code_match = re.search(r'\((\d+)\)', prefix_str)
                            iso_match = re.search(r'\(([A-Za-z]+)\)', prefix_str)
                            
                            if code_match and iso_match and char and eid:
                                code = code_match.group(1)
                                iso = iso_match.group(1).upper()
                                name = prefix_str.replace(f"({code})", "").replace(f"({iso_match.group(1)})", "").replace(char, "").strip()
                                bot_settings["premium_flags"][code] = {"char": char, "iso": iso, "name": name, "id": eid}
                                count += 1
                        except: pass
            else:
                for line in content.splitlines():
                    json_match = re.search(r'(\{.*\})', line)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            char = data.get("emoji")
                            eid = data.get("id")
                            
                            name_part = line[:json_match.start()].strip()
                            name = name_part.replace(char, '').strip() if char else name_part
                            
                            if char and eid and name:
                                bot_settings["premium_apps"][name.upper()] = {"char": char, "id": eid, "name": name}
                                count += 1
                        except: pass
            
            save_db()
            send_message(chat_id, render_body_text(f"{PEM['ok']} Successfully loaded {count} Emojis!"), reply_markup=emoji_settings_keyboard())
            del user_states[chat_id]
            return

        elif state == "wait_for_broadcast":
            msg_id = msg["message_id"]
            send_message(chat_id, render_body_text(f"{PEM['ok']} Broadcast started..."))
            threading.Thread(target=broadcast_copymessage, args=(chat_id, msg_id)).start()
            del user_states[chat_id]
            return

        elif state == "wait_for_txt" and "document" in msg:
            doc = msg["document"]
            if not doc["file_name"].endswith(".txt"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Please upload a .txt file only."))
                return
            file_id = doc["file_id"]
            file_info = requests.get(f"{BASE_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            file_content = requests.get(f"{FILE_URL}{file_path}").text
            
            temp_data[chat_id] = {"numbers": file_content.splitlines(), "filename": doc["file_name"]}
            user_states[chat_id] = "wait_for_service"
            send_message(chat_id, render_body_text(f"{PEM['ok']} File received.\n\n📌 Enter the service name (e.g., WHATSAPP):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_service" and text:
            temp_data[chat_id]["service"] = text.upper()
            user_states[chat_id] = "wait_for_country"
            send_message(chat_id, render_body_text(f"{PEM['ok']} Service set.\n\n🌍 Enter the country name (e.g., YEMEN):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_country" and text:
            country = text.upper()
            temp_data[chat_id]["country"] = country
            user_states[chat_id] = "wait_for_file_rate"
            send_message(chat_id, render_body_text(f"{PEM['ok']} Country set.\n\n💰 Enter the OTP reward rate for this file (e.g. 5.0):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_file_rate" and text:
            try:
                rate = float(text.strip())
            except ValueError:
                send_message(chat_id, render_body_text("❌ Invalid rate! Please enter a number (e.g. 5.0):"), reply_markup=get_cancel_kb())
                return
                
            country = temp_data[chat_id]["country"]
            service = temp_data[chat_id]["service"]
            raw_numbers = temp_data[chat_id]["numbers"]
            
            clean_nums = []
            for num in raw_numbers:
                num = num.strip()
                if num:
                    if not num.startswith('+'): num = '+' + num
                    clean_nums.append(num)
            
            batch_id = str(uuid.uuid4())[:8]
            number_batches[batch_id] = {
                "filename": temp_data[chat_id]["filename"], 
                "service": service, 
                "country": country, 
                "rate": rate,
                "numbers": [{"num": n, "shares": 0, "used_by": []} for n in clean_nums]
            }
            total_uploaded_stats += len(clean_nums)
            save_db()
            
            app_full_name, prem_app_html = get_service_info_html(service)
            prem_flag_html = get_flag_info_html(clean_nums[0]) if clean_nums else f"{PEM['world']} "
            
            broadcast_txt = f"➖➖➖➖➖➖➖➖\n《 NEW NUMBERS 》\n➖➖➖➖➖➖➖➖\n{prem_flag_html} {country} {prem_app_html} {service}\n➖➖➖➖➖➖➖➖\n📤 Total Added: <b>{len(clean_nums)}</b>\n💰 Reward: <b>{rate} TK</b>\n➖➖➖➖➖➖➖➖\nUse /start to get your numbers!"
            broadcast_txt = render_body_text(broadcast_txt)
            
            send_message(chat_id, render_body_text(f"{PEM['ok']} Numbers added to local stock with {rate} TK rate! Starting broadcast..."))
            
            def simple_broadcast(txt):
                b_session = requests.Session()
                url = f"{BASE_URL}/sendMessage"
                for u_id in list(all_known_users):
                    try:
                        b_session.post(url, json={"chat_id": u_id, "text": txt, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=5)
                    except: pass
                    time.sleep(0.035)
            threading.Thread(target=simple_broadcast, args=(broadcast_txt,)).start()
            
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_stex_key" and text:
            key_value = text.strip()
            if key_value and key_value not in bot_settings["stex_keys"]:
                bot_settings["stex_keys"].append(key_value)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"✅ StexSMS API Key Added! Total Keys: {len(bot_settings.get('stex_keys', []))}"), reply_markup=stex_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_voltx_key" and text:
            key_value = text.strip()
            if key_value and key_value not in bot_settings["voltx_keys"]:
                bot_settings["voltx_keys"].append(key_value)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"✅ Voltx API Key Added! Total Keys: {len(bot_settings.get('voltx_keys', []))}"), reply_markup=voltx_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_sc" and text:
            code = text.strip().replace("+", "")
            if "search_countries" not in bot_settings: bot_settings["search_countries"] = []
            if code and code not in bot_settings["search_countries"]:
                bot_settings["search_countries"].append(code)
            save_db()
            delete_message(chat_id, msg["message_id"])
            kb = []
            for idx, c in enumerate(bot_settings.get("search_countries", [])):
                kb.append([{"text": f"❌ Delete {c}", "callback_data": f"del_sc_{idx}", "style": "danger"}])
            kb.append([{"text": "➕ Add Country Code", "callback_data": "add_search_country", "style": "success"}])
            kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🌍 <b>Allowed Search Countries:</b>\nOnly these country codes will be allowed in Search Number."), reply_markup={"inline_keyboard": kb})
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_vsc" and text:
            code = text.strip().replace("+", "")
            if "voltx_search_countries" not in bot_settings: bot_settings["voltx_search_countries"] = []
            if code and code not in bot_settings["voltx_search_countries"]:
                bot_settings["voltx_search_countries"].append(code)
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "voltx_search_country", "id": "internal"})
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_nx_srv_name" and text:
            srv = text.strip().upper()
            if "stex_services" not in bot_settings: bot_settings["stex_services"] = {}
            if srv not in bot_settings["stex_services"]: bot_settings["stex_services"][srv] = {}
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "manage_stex_srv", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_nx_cnt_name" and text:
            cnt = text.strip()
            srv = temp_data[chat_id]["srv"]
            if cnt not in bot_settings["stex_services"][srv]: bot_settings["stex_services"][srv][cnt] = []
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"nx_srv_{srv}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_nx_addr" and text:
            srv, cnt = temp_data[chat_id]["srv"], temp_data[chat_id]["cnt"]
            new_range = text.strip().replace("+", "")
            
            if new_range not in bot_settings["stex_services"][srv][cnt]:
                bot_settings["stex_services"][srv][cnt].append(new_range)
                
                if "search_countries" not in bot_settings:
                    bot_settings["search_countries"] = []
                if new_range not in bot_settings["search_countries"]:
                    bot_settings["search_countries"].append(new_range)
                    
                save_db()
                
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"nx_cnt_{srv}_{cnt}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_srv_name" and text:
            srv = text.strip().upper()
            if "voltx_services" not in bot_settings: bot_settings["voltx_services"] = {}
            if srv not in bot_settings["voltx_services"]: bot_settings["voltx_services"][srv] = {}
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "manage_voltx_srv", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_cnt_name" and text:
            cnt = text.strip()
            srv = temp_data[chat_id]["srv"]
            if cnt not in bot_settings["voltx_services"][srv]: bot_settings["voltx_services"][srv][cnt] = []
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"vx_srv_{srv}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_addr" and text:
            srv, cnt = temp_data[chat_id]["srv"], temp_data[chat_id]["cnt"]
            new_range = text.strip().replace("+", "")
            
            if new_range not in bot_settings["voltx_services"][srv][cnt]:
                bot_settings["voltx_services"][srv][cnt].append(new_range)
                
                if "voltx_search_countries" not in bot_settings:
                    bot_settings["voltx_search_countries"] = []
                if new_range not in bot_settings["voltx_search_countries"]:
                    bot_settings["voltx_search_countries"].append(new_range)
                    
                save_db()
                
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"vx_cnt_{srv}_{cnt}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_for_add_zenex_key" and text:
            key_value = text.strip()
            if key_value and key_value not in bot_settings["zenex_keys"]:
                bot_settings["zenex_keys"].append(key_value)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"✅ Zenex API Key Added! Total Keys: {len(bot_settings.get('zenex_keys', []))}"), reply_markup=zenex_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_zsc" and text:
            code = text.strip().replace("+", "")
            if "zenex_search_countries" not in bot_settings: bot_settings["zenex_search_countries"] = []
            if code and code not in bot_settings["zenex_search_countries"]:
                bot_settings["zenex_search_countries"].append(code)
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "zenex_search_country", "id": "internal"})
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_zx_srv_name" and text:
            srv = text.strip().upper()
            if "zenex_services" not in bot_settings: bot_settings["zenex_services"] = {}
            if srv not in bot_settings["zenex_services"]: bot_settings["zenex_services"][srv] = {}
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "manage_zenex_srv", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_zx_cnt_name" and text:
            cnt = text.strip()
            srv = temp_data[chat_id]["srv"]
            if cnt not in bot_settings["zenex_services"][srv]: bot_settings["zenex_services"][srv][cnt] = []
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"zx_srv_{srv}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_zx_addr" and text:
            srv, cnt = temp_data[chat_id]["srv"], temp_data[chat_id]["cnt"]
            new_range = text.strip().replace("+", "")
            if new_range not in bot_settings["zenex_services"][srv][cnt]:
                bot_settings["zenex_services"][srv][cnt].append(new_range)
                if "zenex_search_countries" not in bot_settings: bot_settings["zenex_search_countries"] = []
                if new_range not in bot_settings["zenex_search_countries"]: bot_settings["zenex_search_countries"].append(new_range)
                save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"zx_cnt_{srv}_{cnt}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_for_add_wm" and text:
            method = text.strip()
            if method and method not in bot_settings["w_methods"]:
                bot_settings["w_methods"].append(method)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_fj" and text:
            channel_id = parse_chat_id(text)
            if channel_id not in bot_settings["fj_channels"]:
                bot_settings["fj_channels"].append(channel_id)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:\n<i>(Note: For private links, use numeric IDs like -100...)</i>"), reply_markup=fj_settings_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return
            
        elif state == "wait_for_add_adm" and text:
            if text.isdigit():
                admin_id = int(text)
                if admin_id not in bot_settings["admins"]:
                    bot_settings["admins"].append(admin_id)
                save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("👥 <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_fw_id" and text:
            group_id = text.strip()
            if group_id and not any(
                str(group.get("chat_id", "")).strip() == group_id
                for group in bot_settings["fw_groups"]
                if isinstance(group, dict)
            ):
                bot_settings["fw_groups"].append(
                    {"chat_id": group_id, "buttons": []}
                )
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return
            
        elif state == "wait_for_add_fw_btn" and text:
            fw_idx = temp_data[chat_id]["fw_idx"]
            if "-" in text:
                parts = text.split("-", 1)
                btn_text = parts[0].strip()
                btn_url = parts[1].strip()
                
                emoji_id = None
                emoji_char = ""
                for ent in msg.get("entities", []):
                    if ent.get("type") == "custom_emoji":
                        emoji_id = ent.get("custom_emoji_id")
                        offset = ent.get("offset", 0)
                        length = ent.get("length", 0)
                        b_text = text.encode('utf-16-le')
                        emoji_char = b_text[offset*2:(offset+length)*2].decode('utf-16-le')
                        break
                
                if emoji_char:
                    btn_text = btn_text.replace(emoji_char, "").strip()
                    
                btn_data = {"text": btn_text, "url": btn_url}
                if emoji_id:
                    btn_data["icon_custom_emoji_id"] = emoji_id
                    
                bot_settings["fw_groups"][fw_idx]["buttons"].append(btn_data)
                save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"🛡 <b>Manage Group:</b> {bot_settings['fw_groups'][fw_idx]['chat_id']}"), reply_markup=specific_fw_group_keyboard(fw_idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return
            
        elif state == "wait_for_otp_link" and text:
            bot_settings["otp_link"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_panel_name" and text:
            p_name = text.strip()
            if not p_name:
                send_message(chat_id, render_body_text("❌ Provider name cannot be empty."), reply_markup=get_cancel_kb())
                return
            t_key = temp_data[chat_id].get("add_type", "api")
            msg_id = temp_data[chat_id]["msg_id"]
            delete_message(chat_id, msg["message_id"])
            
            if t_key == "logc":
                user_states[chat_id] = "wait_for_cpanel_url"
                temp_data[chat_id] = {"msg_id": msg_id, "p_data": {
                    "name": p_name, "type": "Auto Captcha Panel", "status": "ON", "records": 0, "login_status": "⏳ Pending First Login"
                }}
                edit_message(chat_id, msg_id, render_body_text("1️⃣ <b>Login URL</b>\n➡️ Panel এর Login Link দিন:"), reply_markup=get_cancel_kb())
                return
            else:
                bot_settings["panels"].append({
                    "name": p_name, "type": "API Panel", "status": "OFF", "api_url": "", "token": "", "records": 0
                })
                save_db()
                handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_api_panels", "id": "internal"})
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
                return

        elif state == "wait_for_p_api" and text:
            idx = temp_data[chat_id]["p_idx"]
            try:
                api_url = normalize_panel_url(text)
            except ValueError as exc:
                send_message(chat_id, render_body_text(f"❌ {html.escape(str(exc))}"), reply_markup=get_cancel_kb())
                return
            bot_settings["panels"][idx]["api_url"] = api_url
            save_db()
            delete_message(chat_id, msg["message_id"])
            p = bot_settings["panels"][idx]
            ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_p_tok" and text:
            idx = temp_data[chat_id]["p_idx"]
            bot_settings["panels"][idx]["token"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            p = bot_settings["panels"][idx]
            ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_p_fapi" and text:
            idx = temp_data[chat_id]["p_idx"]
            try:
                full_api_url = normalize_panel_url(text)
            except ValueError as exc:
                send_message(chat_id, render_body_text(f"❌ {html.escape(str(exc))}"), reply_markup=get_cancel_kb())
                return
            try:
                if idx < 0 or idx >= len(bot_settings.get("panels", [])):
                    raise ValueError("This provider no longer exists.")
                p = bot_settings["panels"][idx]
                p["full_api_url"] = full_api_url
                # A Full API URL is authoritative. Keeping an older base URL
                # beside it makes debugging ambiguous and can call the wrong
                # endpoint when the panel is tested.
                p["api_url"] = ""
                p["last_api_error"] = ""
                save_db()
                delete_message(chat_id, msg["message_id"])
                success_text = (
                    f"{PEM['ok']} <b>Full API URL saved successfully.</b>\n\n"
                    f"Provider: <b>{html.escape(str(p.get('name', 'Provider')))}</b>\n"
                    f"URL: <code>{html.escape(full_api_url)}</code>\n\n"
                    "এখন <b>Test Connection</b> চাপুন। URL ঠিক থাকলে HTTP status "
                    "এবং পাওয়া real number/OTP sample দেখাবে।"
                )
                send_message(chat_id, render_body_text(success_text))
                ui_text = (
                    f"⚙️ <b>Configure {p['name']}</b>\n\n"
                    f"<b>Type:</b> {p['type']}\n"
                    f"<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n"
                    f"<b>API URL:</b> <code>{p.get('api_url') or 'None'}</code>\n"
                    f"<b>Full API URL:</b> <code>{html.escape(p.get('full_api_url') or 'None')}</code>"
                )
                edit_message(
                    chat_id,
                    temp_data[chat_id]["msg_id"],
                    render_body_text(ui_text),
                    reply_markup=panel_config_keyboard(idx),
                )
                del user_states[chat_id]
                del temp_data[chat_id]
            except Exception as exc:
                send_message(
                    chat_id,
                    render_body_text(
                        f"❌ <b>Full API URL could not be saved.</b>\n"
                        f"<code>{html.escape(str(exc))}</code>"
                    ),
                    reply_markup=get_cancel_kb(),
                )
            return

        elif state == "wait_for_p_rec" and text:
            if text.isdigit():
                idx = temp_data[chat_id]["p_idx"]
                bot_settings["panels"][idx]["records"] = int(text)
                save_db()
                delete_message(chat_id, msg["message_id"])
                p = bot_settings["panels"][idx]
                
                ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
                edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
                del user_states[chat_id]
                del temp_data[chat_id]
            else:
                send_message(chat_id, render_body_text("❌ Please enter a valid number! Try again."), reply_markup=get_cancel_kb())
                return
            return

        elif state == "set_GX":
            msg_id = temp_data[chat_id]["msg_id"]
            key = temp_data[chat_id]["key"]
            try:
                if key in ["min_withdraw", "otp_reward", "refer_reward"]: 
                    bot_settings[key] = float(text)
                elif key == "num_req":
                    bot_settings[key] = max(1, min(50, int(text)))
                elif key == "num_share":
                    # A number is never reusable by another user.  Keep the
                    # legacy field for compatibility, but lock its effective
                    # value to one so the admin UI cannot re-enable sharing.
                    bot_settings[key] = 1
                elif key == "cooldown":
                    bot_settings[key] = max(0, min(3600, int(text)))
                else: 
                    bot_settings[key] = text
                save_db()
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>GX CONTROL PANEL</b>"), reply_markup=GX_control_keyboard())
            except:
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>GX CONTROL PANEL</b>\n\n❌ Invalid value!"), reply_markup=GX_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_withdraw_amount" and text:
            msg_id_to_edit = temp_data[chat_id].get("msg_id")
            try:
                amount = float(text.strip())
                bal = temp_data[chat_id]["balance"]
                min_w = bot_settings['min_withdraw']
                
                if amount < min_w:
                    if msg_id_to_edit: 
                        edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ Minimum withdrawal is {min_w} ৳!\n💰 Balance: {bal} ৳\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return
                if amount > bal:
                    if msg_id_to_edit: 
                        edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ You don't have enough balance!\n💰 Balance: {bal} ৳\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return
                    
                temp_data[chat_id]["amount"] = amount
                user_states[chat_id] = "wait_for_withdraw_number"
                if msg_id_to_edit:
                    edit_message(chat_id, msg_id_to_edit, render_body_text(f"✅ Amount: {amount} ৳\n\n📱 Now send your <b>{temp_data[chat_id]['method']}</b> account number:"), reply_markup=get_cancel_kb())
            except ValueError:
                if msg_id_to_edit: 
                    edit_message(chat_id, msg_id_to_edit, render_body_text("❌ Invalid amount!\n\n📝 Please send a valid number:"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_2fa_key" and text:
            msg_id_to_edit = temp_data.get(chat_id, {}).get("msg_id")
            delete_message(chat_id, msg.get("message_id"))

            if not msg_id_to_edit:
                send_message(chat_id, render_body_text("❌ Error: Message not found. Try again."))
                del user_states[chat_id]
                return

            try:
                secret = text.strip().replace(" ", "")
                totp = pyotp.TOTP(secret)
                code = totp.now()
                remaining_time = 30 - (int(time.time()) % 30)
                
                success_txt = (
                    f"━━━━━━━━━━━━━━━\n"
                    f"《 🔐 <b>2FA CODE</b> 》\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🔐 <b>CODE:</b> <code>{code}</code>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🕓 <b>EXPIRES IN:</b> {remaining_time}s\n"
                    f"━━━━━━━━━━━━━━━"
                )
                kb = [[{"text": f"Click to copy {code}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": code}, "style": "success"}],
                      [{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"ref_2fa_{secret}", "style": "primary"},
                       {"text": "New Code", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "gen_2fa", "style": "danger"}],
                      [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
                
                edit_message(chat_id, msg_id_to_edit, render_body_text(success_txt), reply_markup={"inline_keyboard": kb})
                del user_states[chat_id]
                if chat_id in temp_data: 
                    del temp_data[chat_id]
            except Exception:
                error_txt = "━━━━━━━━━━━━━━━\n《 🔑 <b>ENTER 2FA KEY</b> 》\n━━━━━━━━━━━━━━━\n📝 <b>SEND YOUR 2FA SECRET KEY</b>\n━━━━━━━━━━━━━━━\n❌ <b>Invalid Secret Key! Try again.</b>\n━━━━━━━━━━━━━━━"
                cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_2fa", "style": "danger"}]]}
                edit_message(chat_id, msg_id_to_edit, render_body_text(error_txt), reply_markup=cancel_kb)
            return

        elif state == "wait_for_withdraw_number":
            msg_id_to_edit = temp_data[chat_id].get("msg_id")
            
            method = temp_data[chat_id]["method"]
            amount = temp_data[chat_id]["amount"]
            number = text
            req_id = f"W_{str(uuid.uuid4())[:6].upper()}"
            
            first_name = msg.get("from", {}).get("first_name", "User")
            last_name = msg.get("from", {}).get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()
            
            update_balance(chat_id, -amount, reason="withdrawal_debit")
            pending_withdrawals[req_id] = {"user_id": chat_id, "amount": amount, "method": method, "number": number, "full_name": full_name}
            
            if db:
                try:
                    db.collection('withdrawals').document(req_id).set({
                        "user_id": str(chat_id),
                        "amount": amount,
                        "method": method,
                        "number": str(number)[:80],
                        "full_name": full_name[:120],
                        "status": "pending",
                        "timestamp": postgres.SERVER_TIMESTAMP,
                        "request_message": f"Withdrawal request: {amount} TK via {method}"
                    })
                except: 
                    pass
            record_history(
                chat_id,
                "withdrawal_request",
                message=f"Withdrawal request: {amount} TK via {method}",
                amount=amount,
                status="pending",
                method=method,
                request_id=req_id,
                payment_number=number
            )
                    
            if bot_settings["w_group"]:
                admin_msg = f"🎙 <b>NEW WITHDRAWAL REQUEST</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={chat_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amount} TK\n🍏 <b>NUMBER:</b> <code>{number}</code>\n🏦 <b>METHOD:</b> {method}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
                kb = {"inline_keyboard": [[{"text": "APPROVE", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"wapp_{req_id}", "style": "success"}, {"text": "REJECT", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"wrej_{req_id}", "style": "danger"}]]}
                send_message(bot_settings["w_group"], render_body_text(admin_msg), reply_markup=kb)
            
            kb = {"inline_keyboard": [[{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]}
            success_text = f"{PEM['ok']} Your withdrawal request has been submitted!\n\n🧾 <b>Req ID:</b> {req_id}\n💰 <b>Amount:</b> {amount} ৳\n🏦 <b>Method:</b> {method}\n📱 <b>Number:</b> <code>{number}</code>"
            
            if msg_id_to_edit:
                edit_message(chat_id, msg_id_to_edit, render_body_text(success_text), reply_markup=kb)
            else:
                send_message(chat_id, render_body_text(success_text), reply_markup=kb)
                
            del user_states[chat_id]
            del temp_data[chat_id]
            return

    # --- Regular Commands ---
    if text.startswith("/start"):
        get_user(chat_id)
        
        if db:
            doc = db.collection('users').document(str(chat_id)).get()
            if doc.exists:
                u_data = doc.to_dict()
                if u_data.get("referred_by") and not u_data.get("ref_paid"):
                    inviter = u_data["referred_by"]
                    db.collection('users').document(str(chat_id)).update({"ref_paid": True})
                    reward = bot_settings.get("refer_reward", 0.2)
                    update_balance(inviter, reward)
                    db.collection('users').document(str(inviter)).update({"total_refers": postgres.Increment(1)})
                    trigger_google_sheets_sync()
                    if inviter in user_cache:
                        user_cache[inviter]["total_refers"] = user_cache[inviter].get("total_refers", 0) + 1
                    ref_msg = (
                        f"{PEM['gift']} <b>New Referral !</b>\n"
                        f"------------------\n"
                        f"🔥 <b>You Received {reward} TK</b>\n"
                        f"------------------\n"
                        f"{PEM['user']} <b>From User ID:</b> <code>{chat_id}</code>"
                    )
                    send_message(inviter, render_body_text(ref_msg))
                    
        send_start_ui(chat_id)
            
    elif command == "TRAFFIC":
        txt, markup = build_traffic_ui()
        send_message(chat_id, txt, reply_markup=markup)
        
    elif command == "REFER":
        u_data = get_user(chat_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        c_msg = bot_settings["custom_messages"].get("refer", {})
        
        raw_txt = c_msg.get("text", f"{PEM['gift']} Refer").replace("{ref_link}", ref_link).replace("{total_ref}", str(u_data.get('total_refers', 0))).replace("{ref_reward}", str(bot_settings['refer_reward']))
        txt = render_body_text(raw_txt)
        
        kb = [[{"text": "COPY LINK", "icon_custom_emoji_id": "5192739271886282680", "copy_text": {"text": ref_link}, "style": "success"}]]
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "CLOSE", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif command == "WITHDRAWAL":
        if not bot_settings["withdraw_on"]:
            send_message(chat_id, render_body_text(f"{PEM['no']} Withdrawals are currently disabled."))
            return
        
        u_data = get_user(chat_id)
        bal = u_data.get('balance', 0.0)
        
        c_msg = bot_settings["custom_messages"].get("withdrawal", {})
        raw_txt = c_msg.get("text", "Withdrawal").replace("{bal}", str(bal)).replace("{total_otp}", str(u_data.get('total_otps', 0))).replace("{total_ref}", str(u_data.get('total_refers', 0))).replace("{min_w}", str(bot_settings['min_withdraw']))
        txt = render_body_text(raw_txt)
        
        kb = []
        for m in bot_settings["w_methods"]:
            kb.append([{"text": m.strip(), "icon_custom_emoji_id": "5190899075968441286", "callback_data": f"sel_wm_{m.strip()}", "style": "primary"}])
        
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Cancel", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif command == "ADMIN PANEL" and is_admin(chat_id):
        send_message(chat_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))

    elif command == "GET NUMBER":
        local_srvs = set([b["service"] for b in number_batches.values() if b["numbers"]])
        stex_srvs = set(bot_settings.get("stex_services", {}).keys())
        voltx_srvs = set(bot_settings.get("voltx_services", {}).keys())
        zenex_srvs = set(bot_settings.get("zenex_services", {}).keys())
        all_services = local_srvs.union(stex_srvs).union(voltx_srvs).union(zenex_srvs)
        
        if not all_services:
            send_message(chat_id, render_body_text(f"{PEM['no']} No numbers or services available!"))
        else:
            c_msg = bot_settings["custom_messages"].get("get_number", {})
            txt = render_body_text(c_msg.get("text", f"{PEM['pin']} Select Service"))
            
            apps_db = bot_settings.get("premium_apps", {})
            kb = []
            service_buttons = []
            for s in sorted(
                all_services,
                key=lambda value: (-_service_traffic_count(value), str(value).lower()),
            ):
                emoji_id = "5352694861990501856"
                for app_key, app_data in apps_db.items():
                    if s.upper() == app_key or s.upper() in app_key or app_key in s.upper():
                        if "id" in app_data:
                            emoji_id = app_data["id"]
                            break
                service_name, _ = get_service_info_html(s)
                service_buttons.append(
                    {
                        "text": service_name,
                        "icon_custom_emoji_id": emoji_id,
                        "callback_data": f"g_s_{s}",
                        "style": "primary",
                    }
                )
            service_buttons = _equal_service_button_labels(service_buttons)
            txt = _stretch_service_prompt(txt, service_buttons)
            kb.extend(_two_column_rows(service_buttons))
            
            for b in c_msg.get("buttons", []): 
                b_copy = b.copy()
                if "style" not in b_copy: b_copy["style"] = "primary"
                kb.append([b_copy])
            kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
            
            send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif command == "2FA ONLINE" or text == "🔐 2FA ONLINE":
        txt = "━━━━━━━━━━━━━━━\n《 🔐 <b>2FA ONLINE</b> 》\n━━━━━━━━━━━━━━━\n<i>Generate your 2FA security code instantly using your secret key.</i>\n━━━━━━━━━━━━━━━"
        kb = [[{"text": "Generate 2fa code", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "gen_2fa", "style": "success"}],
              [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
        send_message(chat_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif command == "SUPPORT":
        c_msg = bot_settings["custom_messages"].get("support", {})
        txt = render_body_text(c_msg.get("text", f"{PEM['msg']} Support"))
        if not txt.strip(): txt = render_body_text(f"{PEM['msg']} Support")
        kb = []
        for b in c_msg.get("buttons", []):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
            
        sup_link = bot_settings.get("support_link", "")
        if sup_link:
            kb.insert(0, [{"text": "Contact Support", "icon_custom_emoji_id": "5337302974806922068", "url": sup_link, "style": "success"}])
            
        kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb} if kb else None)

def expire_previous_number(chat_id):
    if chat_id in user_active_sessions:
        prev_data = user_active_sessions[chat_id]
        prev_msg_id = prev_data["msg_id"]
        nums = prev_data["nums"]
        
        for num in nums:
            if num in stex_assigned_numbers: del stex_assigned_numbers[num]
            if num in voltx_assigned_numbers: del voltx_assigned_numbers[num]
            if num in zenex_assigned_numbers: del zenex_assigned_numbers[num]
        save_db()
        
        kb = [[{"text": "Number Expired", "icon_custom_emoji_id": "5336997731481193790", "callback_data": "ignore", "style": "danger"}]]
        try:
            edit_message(chat_id, prev_msg_id, "NEW NUMBER\n", reply_markup={"inline_keyboard": kb})
        except:
            pass
        del user_active_sessions[chat_id]


def _traffic_name_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _service_traffic_count(service):
    target = _traffic_name_key(service)
    current_time = time.time()
    return sum(
        1 for item in recent_traffic
        if _traffic_name_key(item.get("service")) == target
        and current_time - item.get("time", 0) <= 3600
    )


def _country_traffic_count(country):
    target = str(country or "").strip().upper()
    current_time = time.time()
    total = 0
    for item in recent_traffic:
        if current_time - item.get("time", 0) > 3600:
            continue
        iso = str(item.get("iso", "") or "").upper()
        full_name = str(
            get_flag_info_html(iso, return_full_name=True) or ""
        ).upper()
        if target == iso or target == full_name or target in full_name or full_name in target:
            total += 1
    return total


def _top_traffic_countries(service, countries, limit=7):
    """Show at most seven available countries, ranked by live traffic."""
    unique_countries = list(dict.fromkeys(str(country) for country in countries))
    service_key = _traffic_name_key(service)
    current_time = time.time()
    ranked = []
    for index, country in enumerate(unique_countries):
        service_count = sum(
            1 for item in recent_traffic
            if _traffic_name_key(item.get("service")) == service_key
            and current_time - item.get("time", 0) <= 3600
            and (
                str(item.get("iso", "")).upper() == country.upper()
                or str(get_flag_info_html(
                    str(item.get("iso", "")), return_full_name=True
                ) or "").upper() == country.upper()
            )
        )
        ranked.append((
            service_count,
            _country_traffic_count(country),
            country.lower(),
            index,
            country,
        ))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    return [item[-1] for item in ranked[:limit]]


def _two_column_rows(buttons):
    """Arrange inline buttons two per row for compact mobile layouts."""
    rows = []
    current = []
    for button in buttons:
        current.append(button)
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows


def _equal_service_button_labels(buttons, minimum_width=16):
    """Give service buttons a consistent, slightly roomier visual width."""
    if not buttons:
        return buttons
    longest = max(
        len(re.sub(r"<[^>]+>", "", str(button.get("text", ""))))
        for button in buttons
        if isinstance(button, dict)
    )
    target_width = max(minimum_width, longest)
    padded = []
    for button in buttons:
        if not isinstance(button, dict):
            continue
        item = button.copy()
        label = str(item.get("text", "")).strip()
        # Non-breaking spaces keep Telegram from collapsing the alignment
        # padding while keeping the service name itself unchanged.
        item["text"] = f"\u00a0{label.center(target_width)}\u00a0"
        padded.append(item)
    return padded


def _stretch_service_prompt(text, buttons):
    """Make the service prompt visually span the two-column service row."""
    if not text or not buttons:
        return text
    label_width = max(
        len(re.sub(r"<[^>]+>", "", str(button.get("text", ""))))
        for button in buttons
        if isinstance(button, dict)
    )
    visible_text = re.sub(r"<[^>]+>", "", str(text))
    # Add a little extra room for Telegram's inline-button icon spacing so
    # the prompt bubble reaches the right edge of the service row.
    target_width = (label_width * 2) + 9
    extra_spaces = max(0, target_width - len(visible_text))
    padding = "\u00a0" * extra_spaces
    return f"{text}{padding}"


def _compact_number_label(number):
    """Show the complete number while keeping one consistent label format."""
    value = str(number or "").strip()
    clean = re.sub(r"[^\d]", "", value)
    return f"+{clean}" if clean else value


# ==========================================
# Callback Query Handler
# ==========================================
def handle_callback(call):
    global total_assigned_stats
    chat_id = call["message"]["chat"]["id"]
    chat_type = call["message"]["chat"].get("type", "private")
    data = call.get("data", "")

    if not data.startswith("test_p_conn_") and not data.startswith("c_n_") and not data.startswith("g_c_"):
        try: threading.Thread(target=answer_callback, args=(call["id"],)).start()
        except: pass

    if chat_type != "private" and not (data.startswith("wapp_") or data.startswith("wrej_")):
        return

    msg_id = call["message"]["message_id"]

    if chat_type == "private":
        if is_user_banned(chat_id):
            answer_callback(call["id"], "🚫 You are banned from using this bot!", show_alert=True)
            return

        if data in ("set_lang_EN", "set_lang_BN"):
            language = set_user_language(chat_id, data.rsplit("_", 1)[-1])
            answer_callback(call["id"], "Language saved!" if language == "EN" else "ভাষা সেভ হয়েছে!")
            delete_message(chat_id, msg_id)
            if not check_force_join(chat_id):
                send_force_join_msg(chat_id)
            else:
                send_start_ui(chat_id)
            return

        if not check_force_join(chat_id) and data != "check_fj":
            send_force_join_msg(chat_id)
            return

    if data == "check_fj":
        if check_force_join(chat_id):
            delete_message(chat_id, msg_id)
            send_message(chat_id, render_body_text(f"{PEM['ok']} Thanks for joining! You can now use the bot."), reply_markup=main_menu(chat_id))
            
            if db:
                doc = db.collection('users').document(str(chat_id)).get()
                if doc.exists:
                    u_data = doc.to_dict()
                    if u_data.get("referred_by") and not u_data.get("ref_paid"):
                        inviter = u_data["referred_by"]
                        db.collection('users').document(str(chat_id)).update({"ref_paid": True})
                        reward = bot_settings.get("refer_reward", 0.2)
                        update_balance(inviter, reward)
                        db.collection('users').document(str(inviter)).update({"total_refers": postgres.Increment(1)})
                        trigger_google_sheets_sync()
                        if inviter in user_cache:
                            user_cache[inviter]["total_refers"] = user_cache[inviter].get("total_refers", 0) + 1
                        ref_msg = (
                            f"{PEM['gift']} <b>New Referral !</b>\n"
                            f"------------------\n"
                            f"🔥 <b>You Received {reward} TK</b>\n"
                            f"------------------\n"
                            f"{PEM['user']} <b>From User ID:</b> <code>{chat_id}</code>"
                        )
                        send_message(inviter, render_body_text(ref_msg))
        else:
            answer_callback(call["id"], "❌ You haven't joined all channels yet!", show_alert=True)
        return

    if data in {
        "backup_all_data", "restore_all_data", "delete_all_data", "delete_all_data_yes",
        "restore_confirm", "restore_cancel", "google_sheet_status", "google_sheet_sync_now"
    } and not is_admin(chat_id):
        answer_callback(call["id"], "🚫 Admin only.", show_alert=True)
        return

    if data == "backup_all_data":
        answer_callback(call["id"], "Preparing backup…")
        send_full_backup(chat_id)
        return

    if data == "restore_all_data":
        user_states[chat_id] = "wait_for_restore_json"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                "📥 <b>RESTORE ALL DATA</b>\n\n"
                "Upload a Google Sheets .xlsx file, or a bot .json/.csv backup now.\n"
                "After upload, the bot will show a final confirmation before replacing "
                "the current Users, Withdrawals and History data."
            ),
            reply_markup={"inline_keyboard": [[
                {"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176",
                 "callback_data": "back_to_admin", "style": "danger"}
            ]]}
        )
        return

    if data == "restore_confirm":
        restore_backup = temp_data.get(chat_id, {}).get("restore_backup")
        if not restore_backup:
            answer_callback(call["id"], "❌ Backup session expired. Upload it again.", show_alert=True)
            return
        try:
            restore_summary = restore_full_backup(restore_backup)
            with google_sync_lock:
                sheets_synced = sync_to_google_sheets(force=True)
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            answer_callback(call["id"], "✅ Data merge completed.", show_alert=True)
            if restore_summary.get("full_state"):
                restore_details = (
                    f"Users: {restore_summary['users']}\n"
                    f"Withdrawals: {restore_summary['withdrawals']}\n"
                    f"History: {restore_summary['history']}\n"
                    f"Number files: {restore_summary['number_batches']}\n"
                    f"Google Sheets sync: {'✅' if sheets_synced else '⚠️ not configured/failed'}"
                )
            else:
                restore_details = (
                    f"Users restored: {restore_summary['users']}\n"
                    f"Withdrawals: {restore_summary['withdrawals']}\n"
                    f"History: {restore_summary['history']}\n"
                    f"Google Sheets sync: {'✅' if sheets_synced else '⚠️ not configured/failed'}"
                )
            edit_message(
                chat_id,
                msg_id,
                render_body_text(
                    f"{PEM['ok']} <b>Restore completed successfully.</b>\n"
                    f"{restore_details}"
                ),
                reply_markup=admin_panel_keyboard(chat_id),
            )
        except Exception as exc:
            answer_callback(call["id"], "❌ Restore failed.", show_alert=True)
            edit_message(
                chat_id,
                msg_id,
                render_body_text(f"❌ Restore failed: <code>{html.escape(str(exc))}</code>"),
                reply_markup=admin_panel_keyboard(chat_id),
            )
        return

    if data == "restore_cancel":
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        answer_callback(call["id"], "Restore cancelled.")
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))
        return

    if data == "delete_all_data":
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                "⚠️ <b>DELETE ALL BOT DATA?</b>\n\n"
                "This will remove users, balances, history, withdrawals, number stock, "
                "API keys and custom settings from the bot and clear the Google Sheets mirror.\n"
                "The owner account and safe default settings will remain so the bot can start again."
            ),
            reply_markup={"inline_keyboard": [
                [{"text": "YES, DELETE EVERYTHING", "icon_custom_emoji_id": "5422557736330106570",
                  "callback_data": "delete_all_data_yes", "style": "danger"}],
                [{"text": "NO, GO BACK", "icon_custom_emoji_id": "5267490665117274959",
                  "callback_data": "back_to_admin", "style": "primary"}],
            ]}
        )
        return

    if data == "delete_all_data_yes":
        delete_all_bot_data()
        with google_sync_lock:
            sync_to_google_sheets(force=True)
        answer_callback(call["id"], "✅ All bot data deleted.", show_alert=True)
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))
        return

    if data == "google_sheet_status":
        edit_message(
            chat_id,
            msg_id,
            render_body_text(get_google_sheet_status_text()),
            reply_markup={"inline_keyboard": [
                [{"text": "Sync Now", "icon_custom_emoji_id": "5465368548702446780",
                  "callback_data": "google_sheet_sync_now", "style": "success"}],
                [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176",
                  "callback_data": "back_to_admin", "style": "primary"}],
            ]}
        )
        return

    if data == "google_sheet_sync_now":
        with google_sync_lock:
            synced = sync_to_google_sheets(force=True)
        answer_callback(
            call["id"],
            "✅ Google Sheet updated." if synced else "❌ Google Sheet sync failed. Check configuration.",
            show_alert=True,
        )
        edit_message(
            chat_id,
            msg_id,
            render_body_text(get_google_sheet_status_text()),
            reply_markup={"inline_keyboard": [
                [{"text": "Sync Now", "icon_custom_emoji_id": "5465368548702446780",
                  "callback_data": "google_sheet_sync_now", "style": "success"}],
                [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176",
                  "callback_data": "back_to_admin", "style": "primary"}],
            ]}
        )
        return

    if data == "export_data":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admin only.", show_alert=True)
            return
        edit_message(chat_id, msg_id, render_body_text(
            loading_html("Preparing clean user-data export...")
        ))
        send_data_export(chat_id)
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))
        return

    if data == "close_msg":
        delete_message(chat_id, msg_id)

    elif data == "ignore":
        # Informational/status buttons use this callback so Telegram clears
        # the loading state instead of leaving a dead callback spinning.
        answer_callback(call["id"])
        
    elif data == "cancel_state":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        delete_message(chat_id, msg_id)

    elif data == "cancel_2fa":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        txt = "━━━━━━━━━━━━━━━\n《 🔐 <b>2FA ONLINE</b> 》\n━━━━━━━━━━━━━━━\n<i>Generate your 2FA security code instantly using your secret key.</i>\n━━━━━━━━━━━━━━━"
        kb = [[{"text": "Generate 2fa code", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "gen_2fa", "style": "success"}],
              [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

    elif data == "gen_2fa":
        user_states[chat_id] = "wait_for_2fa_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        txt = "━━━━━━━━━━━━━━━\n《 🔑 <b>ENTER 2FA KEY</b> 》\n━━━━━━━━━━━━━━━\n📝 <b>SEND YOUR 2FA SECRET KEY</b>\n━━━━━━━━━━━━━━━"
        kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_2fa", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
        answer_callback(call["id"])

    elif data.startswith("ref_2fa_"):
        secret = data.replace("ref_2fa_", "")
        try:
            totp = pyotp.TOTP(secret)
            code = totp.now()
            remaining_time = 30 - (int(time.time()) % 30)
            
            success_txt = (
                f"━━━━━━━━━━━━━━━\n"
                f"《 🔐 <b>2FA CODE</b> 》\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🔐 <b>CODE:</b> <code>{code}</code>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🕓 <b>EXPIRES IN:</b> {remaining_time}s\n"
                f"━━━━━━━━━━━━━━━"
            )
            kb = [[{"text": f"Click to copy {code}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": code}, "style": "success"}],
                  [{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"ref_2fa_{secret}", "style": "primary"},
                   {"text": "New Code", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "gen_2fa", "style": "danger"}],
                  [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
            
            edit_message(chat_id, msg_id, render_body_text(success_txt), reply_markup={"inline_keyboard": kb})
        except:
            answer_callback(call["id"], "❌ Error refreshing code!", show_alert=True)

    elif data == "cancel_GX_edit":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>GX CONTROL PANEL</b>"), reply_markup=GX_control_keyboard())
        
    elif data == "refresh_traffic":
        txt, markup = build_traffic_ui()
        edit_message(chat_id, msg_id, txt, reply_markup=markup)
        answer_callback(call["id"], "✅ Traffic Refreshed!", show_alert=False)

    elif data.startswith("exp_rng_"):
        srv_query = data.replace("exp_rng_", "")
        
        country_stats = {}
        current_time = time.time()
        for t in recent_traffic:
            if current_time - t.get("time", 0) <= 3600:
                if t.get("service", "").startswith(srv_query):
                    iso = t.get("iso", "XX")
                    flag = t.get("flag", "🌍")
                    if iso not in country_stats:
                        country_stats[iso] = {"count": 0, "flag": flag}
                    country_stats[iso]["count"] += 1
        
        if not country_stats:
            answer_callback(call["id"], "❌ No recent traffic found for this service!", show_alert=True)
            return
            
        kb = []
        for iso, c_data in sorted(country_stats.items(), key=lambda x: x[1]["count"], reverse=True):
            count = c_data["count"]
            c_name = iso
            emoji_id = "5780471598922337683"
            for code, fdata in bot_settings.get("premium_flags", {}).items():
                if fdata.get("iso") == iso:
                    c_name = fdata.get("name", iso)
                    if "id" in fdata: emoji_id = fdata["id"]
                    break
            
            btn_text = f"{c_name} ({iso}) - {count} OTP"
            kb.append([{"text": btn_text, "icon_custom_emoji_id": emoji_id, "callback_data": f"exp_c_{srv_query}_{iso}", "style": "primary"}])
            
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "refresh_traffic", "style": "danger"}])
        
        app_full_name, prem_app_html = get_service_info_html(srv_query)
        edit_message(chat_id, msg_id, render_body_text(f"📊 <b>Explore Service: {prem_app_html} {app_full_name}</b>\n\nSelect a country to view available ranges:"), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

    elif data.startswith("exp_c_"):
        parts = data.split("_")
        srv_query = parts[2]
        iso_query = parts[3]
        
        nums = []
        current_time = time.time()
        for t in recent_traffic:
            if current_time - t.get("time", 0) <= 3600:
                if t.get("service", "").startswith(srv_query) and t.get("iso") == iso_query:
                    num = t.get("real_range", t.get("number", "").replace("X", "").replace("x", "")).replace("+", "").strip()
                    if num: nums.append(num)
        
        if not nums:
            answer_callback(call["id"], "❌ No recent numbers found for this country!", show_alert=True)
            return
            
        known_ranges = set()
        for s_name, c_dict in bot_settings.get("stex_services", {}).items():
            for c_name, r_list in c_dict.items():
                for r in r_list:
                    known_ranges.add(r.replace("X", "").replace("x", ""))
                    
        sorted_known = sorted(list(known_ranges), key=len, reverse=True)
        
        r_counts = Counter()
        for num in nums:
            matched = False
            for r in sorted_known:
                if num.startswith(r):
                    r_counts[r] += 1
                    matched = True
                    break
            if not matched:
                if len(num) >= 7:
                    r_counts[num[:7]] += 1
                else:
                    r_counts[num] += 1
                    
        r_list = r_counts.most_common(12)
        
        kb = []
        temp_row = []
        for r, count in r_list:
            clean_r = str(r).replace("X", "").replace("x", "")
            temp_row.append({"text": f"{clean_r} ({count})", "icon_custom_emoji_id": "5352862640592949843", "callback_data": f"c_n_s_{clean_r}_{srv_query}", "style": "primary"})
            if len(temp_row) == 2:
                kb.append(temp_row)
                temp_row = []
        if temp_row:
            kb.append(temp_row)
            
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"exp_rng_{srv_query}", "style": "danger"}])
        
        app_full_name, prem_app_html = get_service_info_html(srv_query)
        prem_flag_html = get_flag_info_html(iso_query)
        
        edit_message(chat_id, msg_id, render_body_text(f"📊 <b>Ranges for {prem_app_html} {app_full_name} - {prem_flag_html} {iso_query}</b>\n\nClick on any range to copy it."), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

    elif data == "user_management":
        edit_message(chat_id, msg_id, get_user_management_text(), reply_markup=user_management_keyboard())

    elif data == "um_manage_balance":
        user_states[chat_id] = "wait_for_um_bal_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to Manage Balance:"), reply_markup=get_cancel_kb())
        
    elif data == "um_ban_unban":
        user_states[chat_id] = "wait_for_um_ban_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to Ban or Unban:"), reply_markup=get_cancel_kb())

    elif data == "um_user_profile":
        user_states[chat_id] = "wait_for_um_prof_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to View Profile:"), reply_markup=get_cancel_kb())

    elif data == "menu_design_list":
        edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Menu Design Editor</b>\n\nSelect a menu block to edit its Body Text and Inline Buttons. You can use Premium Emojis too!"), reply_markup=menu_design_list_keyboard())

    elif data == "md_reset_defaults":
        bot_settings["custom_messages"] = DEFAULT_CUSTOM_MESSAGES.copy()
        save_db()
        answer_callback(call["id"], "✅ Resetted to Premium Defaults!", show_alert=True)

    elif data.startswith("md_edit_"):
        answer_callback(call["id"])
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        key = data.replace("md_edit_", "")
        cm_text = render_body_text(bot_settings["custom_messages"].get(key, {}).get("text", "..."))
        try:
            edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Editing: {key.upper()}</b>\n\nPreview of current Text:\n{cm_text}"), reply_markup=menu_edit_options_keyboard(key))
        except: pass

    elif data.startswith("md_text_"):
        key = data.replace("md_text_", "")
        user_states[chat_id] = "wait_for_menu_text"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"📝 <b>Edit Body: {key.upper()}</b>\n\nSend the new text. You can use Premium Emojis directly here.\n(Use standard HTML like <b>bold</b>, <i>italic</i> for formatting)"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{key}", "style": "danger"}]]})

    elif data.startswith("md_btns_"):
        answer_callback(call["id"]) 
        if chat_id in user_states: del user_states[chat_id] 
        if chat_id in temp_data: del temp_data[chat_id]
        key = data.replace("md_btns_", "")
        try:
            edit_message(chat_id, msg_id, render_body_text(f"⚙️ <b>Edit Inline Buttons: {key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(key))
        except: pass

    elif data.startswith("md_addbtn_"):
        key = data.replace("md_addbtn_", "")
        user_states[chat_id] = "wait_for_menu_btn"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"➕ <b>Add Button: {key.upper()}</b>\n\nSend custom button in this format:\n<code>Button Text - https://link.com</code>\n\n<i>(Only normal Emojis supported here!)</i>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_btns_{key}", "style": "danger"}]]})

    elif data.startswith("md_delbtn_"):
        parts = data.split("_")
        key = parts[2]
        b_idx = int(parts[3])
        if b_idx < len(bot_settings["custom_messages"][key]["buttons"]):
            del bot_settings["custom_messages"][key]["buttons"][b_idx]
            save_db()
            answer_callback(call["id"], "✅ Button Deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"⚙️ <b>Edit Inline Buttons: {key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(key))

    elif data.startswith("sel_wm_"):
        method = data.replace("sel_wm_", "")
        bal = get_user(chat_id).get('balance', 0.0)
        min_w = bot_settings['min_withdraw']
        
        if bal < min_w:
            answer_callback(call["id"], f"❌ আপনার ব্যালেন্স অপর্যাপ্ত! মিনিমাম {min_w} ৳ প্রয়োজন।", show_alert=True)
            return
            
        temp_data[chat_id] = {"method": method, "balance": bal, "msg_id": msg_id}
        user_states[chat_id] = "wait_for_withdraw_amount"
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} Method: {method}\n💰 Available Balance: {bal} ৳\n\n📝 Enter the amount you want to withdraw (Min: {min_w} ৳):"), reply_markup=get_cancel_kb())
        answer_callback(call["id"])

    elif data == "test_message_flow":
        user_states[chat_id] = "wait_for_test_service"
        temp_data[chat_id] = {}
        edit_message(chat_id, msg_id, render_body_text("🧪 <b>Test Mode</b>\n\n📝 Send the Service Name (e.g., IG):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]]})

    elif data == "manage_emojis":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['star']} <b>Premium Emoji Management</b>\n\nUpload your TXT files or manually add them below:"), reply_markup=emoji_settings_keyboard())

    elif data == "up_flags_txt":
        user_states[chat_id] = "wait_for_flag_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the <b>Flag Emojis</b> <code>.txt</code> file."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "up_apps_txt":
        user_states[chat_id] = "wait_for_app_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the <b>Service Apps</b> <code>.txt</code> file."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "add_single_emoji":
        user_states[chat_id] = "wait_for_emoji_extract"
        edit_message(chat_id, msg_id, render_body_text("📝 যেকোনো একটি Premium Emoji সেন্ড করুন (যেমন: 🇧🇩 বা 🚫):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "dl_flags_txt":
        def generate_emoji_txt(mode):
            if mode == "flags":
                lines = []
                for code, data in bot_settings.get("premium_flags", {}).items():
                    line = f"{data['char']} ({code}) ({data.get('iso', 'XX')}) {data.get('name', '')} {json.dumps({'emoji': data['char'], 'id': data.get('id', '')})}"
                    lines.append(line)
                return "\n".join(lines)
            else:
                lines = []
                for name, data in bot_settings.get("premium_apps", {}).items():
                    line = f"{data['char']} {data.get('name', name)} {json.dumps({'emoji': data['char'], 'id': data.get('id', '')})}"
                    lines.append(line)
                return "\n".join(lines)
                
        content = generate_emoji_txt("flags")
        if content:
            send_document(chat_id, "Flag_Emojis.txt", content)
            answer_callback(call["id"], "✅ Downloaded!")
        else:
            answer_callback(call["id"], "❌ No Flag Emojis found!", show_alert=True)

    elif data == "dl_apps_txt":
        def generate_emoji_txt(mode):
            if mode == "flags":
                lines = []
                for code, data in bot_settings.get("premium_flags", {}).items():
                    line = f"{data['char']} ({code}) ({data.get('iso', 'XX')}) {data.get('name', '')} {json.dumps({'emoji': data['char'], 'id': data.get('id', '')})}"
                    lines.append(line)
                return "\n".join(lines)
            else:
                lines = []
                for name, data in bot_settings.get("premium_apps", {}).items():
                    line = f"{data['char']} {data.get('name', name)} {json.dumps({'emoji': data['char'], 'id': data.get('id', '')})}"
                    lines.append(line)
                return "\n".join(lines)
                
        content = generate_emoji_txt("apps")
        if content:
            send_document(chat_id, "Service_Apps.txt", content)
            answer_callback(call["id"], "✅ Downloaded!")
        else:
            answer_callback(call["id"], "❌ No App Emojis found!", show_alert=True)

    elif data == "del_all_flags":
        bot_settings["premium_flags"] = {}
        save_db()
        answer_callback(call["id"], "✅ All Premium Flags Deleted Successfully!", show_alert=True)

    elif data == "broadcast_msg":
        user_states[chat_id] = "wait_for_broadcast"
        edit_message(chat_id, msg_id, render_body_text("📢 <b>Broadcast Mode</b>\n\nSend the message you want to broadcast (Text, Photo, Video, File etc)."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]})

    elif data == "upload_num":
        user_states[chat_id] = "wait_for_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the numbers in a <b>.txt</b> file."), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]})

    elif data == "delete_files":
        kb = []
        for b_id, b_data in number_batches.items():
            kb.append([{"text": f"{b_data['filename']} ({len(b_data['numbers'])})", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"del_b_{b_id}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "primary"}])
        txt = "🗑 Select a file to delete:" if len(kb) > 1 else f"{PEM['no']} No files found."
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_b_"):
        b_id = data.split("del_b_")[1]
        if b_id in number_batches:
            del number_batches[b_id]
            save_db()
            answer_callback(call["id"], "✅ File deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "delete_files", "id": call["id"]})

    elif data == "show_used":
        kb = {"inline_keyboard": [[{"text": "Download TXT", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_used", "style": "primary"}], [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} <b>Total Used Numbers:</b> {len(used_numbers_list)}"), reply_markup=kb)

    elif data == "show_unused":
        unused_count = sum(len(b["numbers"]) for b in number_batches.values())
        kb = {"inline_keyboard": [[{"text": "Download TXT", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_unused", "style": "primary"}], [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['rocket']} <b>Total Unused Numbers:</b> {unused_count}"), reply_markup=kb)

    elif data == "dl_used":
        if not used_numbers_list:
            answer_callback(call["id"], "❌ No used numbers found!", show_alert=True)
            return
        content = "\n".join(used_numbers_list).encode('utf-8')
        send_document(chat_id, "used_numbers.txt", content)
        answer_callback(call["id"])

    elif data == "dl_unused":
        unused_list = [n["num"] for b in number_batches.values() for n in b["numbers"]]
        if not unused_list:
            answer_callback(call["id"], "❌ No unused numbers found!", show_alert=True)
            return
        content = "\n".join(unused_list).encode('utf-8')
        send_document(chat_id, "unused_numbers.txt", content)
        answer_callback(call["id"])

    elif data == "lb_main":
        txt = f"━━━━━━━━━━━━━━━\n《 {PEM['admin']} <b>LEADER BOARD MENU</b> 》\n━━━━━━━━━━━━━━━\n<i>Select a category to view the top performers or history.</i>\n━━━━━━━━━━━━━━━"
        kb = [
            [{"text": "Top Referrers", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "lb_top_refs", "style": "primary"}],
            [{"text": "Top OTP Receivers", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "lb_top_otps", "style": "primary"}],
            [{"text": "Withdrawal History", "icon_custom_emoji_id": "5348469219761626211", "callback_data": "lb_w_history", "style": "success"}],
            [{"text": "Back to Admin", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
        ]
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("lb_"):
        sub = data.replace("lb_", "")
        edit_message(chat_id, msg_id, render_body_text(
            loading_html("<i>Fetching Data...</i>")
        ))
        
        num_map = {"1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣", "0": "0️⃣"}
        def get_p_num(n): return "".join([num_map.get(c, c) for c in str(n)])
        
        try:
            if sub == "top_refs":
                title, field, limit, icon = "TOP 5 REFERRERS", "total_refers", 5, PEM.get('user', '👥')
                users = db.collection('users').order_by(field, direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for u in users:
                    d = u.to_dict()
                    if d.get(field, 0) > 0:
                        p = "└" if count == limit else "├"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "└ <i>No data found.</i>\n"

            elif sub == "top_otps":
                title, field, limit, icon = "TOP 5 OTP RECEIVERS", "total_otps", 5, PEM.get('msg', '📩')
                users = db.collection('users').order_by(field, direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for u in users:
                    d = u.to_dict()
                    if d.get(field, 0) > 0:
                        p = "└" if count == limit else "├"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "└ <i>No data found.</i>\n"

            elif sub == "w_history":
                title, limit, icon = "LAST 10 WITHDRAWALS", 10, PEM.get('money', '💸')
                ws = db.collection('withdrawals').order_by('timestamp', direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for w in ws:
                    d = w.to_dict()
                    s = str(d.get('status','Pending')).lower()
                    stat_icon = PEM.get('ok','✅') if s in ["approved","success"] else PEM.get('no','❌') if s=="rejected" else "⏳"
                    uid = d.get('user_id','User')
                    p = "└" if count == limit else "├"
                    res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={uid}'>{uid}</a> ➔ <b>{d.get('amount',0)}৳</b> {stat_icon}\n"
                    count += 1
                if not res_txt: res_txt = "└ <i>No history found.</i>\n"

            final_msg = f"━━━━━━━━━━━━━━━\n{icon} <b>{title}</b>\n━━━━━━━━━━━━━━━\n{res_txt}━━━━━━━━━━━━━━━"
            kb = [[{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": data, "style": "success"}, {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]
            edit_message(chat_id, msg_id, render_body_text(final_msg), reply_markup={"inline_keyboard": kb})

        except Exception as e:
            edit_message(chat_id, msg_id, render_body_text(f"❌ Error: {e}"), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]})

    elif data == "back_to_admin":
        if chat_id in user_states: del user_states[chat_id]
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))

    elif data == "toggle_join_notify":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admin only.", show_alert=True)
            return
        settings = bot_settings.setdefault("join_notifications", {})
        admin_key = str(chat_id)
        settings[admin_key] = not get_join_notification_status(chat_id)
        save_db()
        status = "ON" if settings[admin_key] else "OFF"
        answer_callback(call["id"], f"User join notifications: {status}")
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard(chat_id))
        
    elif data == "system_settings":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>System Settings</b>\nManage advanced bot configurations below:"), reply_markup=system_settings_keyboard())

    elif data == "stex_control":
        edit_message(chat_id, msg_id, render_body_text(f"🌐 <b>StexSMS Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('stex_keys', []))}\nManage your StexSMS API Keys below:"), reply_markup=stex_control_keyboard())

    elif data == "toggle_stex_auto":
        bot_settings["stex_auto"] = not bot_settings.get("stex_auto", False)
        save_db()
        edit_message(chat_id, msg_id, render_body_text(f"🌐 <b>StexSMS Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('stex_keys', []))}\nManage your StexSMS API Keys below:"), reply_markup=stex_control_keyboard())
        answer_callback(call["id"], f"✅ Stex Auto Range is now {'ON' if bot_settings['stex_auto'] else 'OFF'}!", show_alert=False)

    elif data == "add_stex_key":
        user_states[chat_id] = "wait_for_add_stex_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new StexSMS API Key (e.g. nxa_...):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "danger"}]]})

    elif data == "view_stex_keys":
        kb = []
        for idx, key in enumerate(bot_settings.get("stex_keys", [])):
            safe_name = key[:10] + "..." if len(key)>10 else key
            kb.append([{"text": f"Delete {safe_name}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_nxa_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🗑 <b>Select StexSMS Key to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_nxa_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("stex_keys", [])):
            del bot_settings["stex_keys"][idx]
            save_db()
            answer_callback(call["id"], "✅ StexSMS Key Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "view_stex_keys", "id": call["id"]})

    elif data == "stex_search_country":
        kb = []
        for idx, c in enumerate(bot_settings.get("search_countries", [])):
            kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_sc_{idx}", "style": "danger"}])
        kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_search_country", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🌍 <b>Allowed Search Countries:</b>\nOnly these country codes will be allowed in Search Number."), reply_markup={"inline_keyboard": kb})

    elif data == "add_search_country":
        user_states[chat_id] = "wait_for_add_sc"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Country Code (e.g. 880 or 92):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_search_country", "style": "danger"}]]})

    elif data.startswith("del_sc_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("search_countries", [])):
            del bot_settings["search_countries"][idx]
            save_db()
            answer_callback(call["id"], "✅ Country Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "stex_search_country", "id": call["id"]})

    elif data == "manage_stex_srv":
        kb = []
        srvs = bot_settings.get("stex_services", {})
        apps_db = bot_settings.get("premium_apps", {})
        for srv in srvs:
            emoji_id = "5257969839313526622"
            for app_key, app_data in apps_db.items():
                if srv.upper() == app_key or srv.upper() in app_key or app_key in srv.upper():
                    if "id" in app_data:
                        emoji_id = app_data["id"]
                        break
            kb.append([{"text": f"{srv}", "icon_custom_emoji_id": emoji_id, "callback_data": f"nx_srv_{srv}", "style": "primary"}])
        kb.append([{"text": "Add New Service", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "nx_add_srv", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "danger"}])
        edit_message(chat_id, msg_id, render_body_text("📦 <b>StexSMS Services Manager</b>\nManage your API-based dynamic services below:"), reply_markup={"inline_keyboard": kb})

    elif data == "nx_add_srv":
        user_states[chat_id] = "wait_nx_srv_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Enter Service Name (e.g. TELEGRAM):"), reply_markup=get_cancel_kb())

    elif data.startswith("nx_srv_"):
        srv = data.replace("nx_srv_", "")
        kb = []
        countries = bot_settings["stex_services"].get(srv, {})
        flags_db = bot_settings.get("premium_flags", {})
        for c in countries:
            emoji_id = "5780471598922337683"
            for flag_code, flag_data in flags_db.items():
                iso = flag_data.get("iso", "").upper()
                name = flag_data.get("name", "").upper()
                if c.upper() == iso or c.upper() == name or c.upper() in name or name in c.upper():
                    if "id" in flag_data:
                        emoji_id = flag_data["id"]
                        break
            kb.append([{"text": f"{c} ({len(countries[c])} Ranges)", "icon_custom_emoji_id": emoji_id, "callback_data": f"nx_cnt_{srv}_{c}", "style": "primary"}])
        kb.append([{"text": "Add Country", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"nx_add_cnt_{srv}", "style": "success"}])
        kb.append([{"text": "Delete Service", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"nx_del_srv_{srv}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_stex_srv", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📂 <b>Service: {srv}</b>\nManage countries for this service:"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("nx_add_cnt_"):
        srv = data.replace("nx_add_cnt_", "")
        user_states[chat_id] = "wait_nx_cnt_name"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv}
        edit_message(chat_id, msg_id, render_body_text(f"🌍 Enter Country Name for <b>{srv}</b> (e.g. BD, INDIA):"), reply_markup=get_cancel_kb())

    elif data.startswith("nx_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        ranges = bot_settings["stex_services"][srv].get(cnt, [])
        
        kb = []
        row = []
        for r in ranges:
            row.append({"text": f"Delete {r}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"nx_dr_{srv}_{cnt}_{r}", "style": "danger"})
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)
        
        kb.append([{"text": "Add Range", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"nx_addr_{srv}_{cnt}", "style": "success"}])
        kb.append([{"text": "Delete Entire Country", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"nx_del_cnt_{srv}_{cnt}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"nx_srv_{srv}", "style": "primary"}])
        
        txt = f"📍 <b>Service: {srv} | Country: {cnt}</b>\n\n<b>Total Ranges:</b> {len(ranges)}\n<i>Click on a range below to delete it, or add a new one.</i>"
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("nx_addr_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        user_states[chat_id] = "wait_nx_addr"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv, "cnt": cnt}
        edit_message(chat_id, msg_id, render_body_text(f"📝 Send the new Range for <b>{cnt}</b> (e.g. 88017):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"nx_cnt_{srv}_{cnt}", "style": "danger"}]]})

    elif data.startswith("nx_dr_"):
        parts = data.split("_")
        srv, cnt, rng = parts[2], parts[3], parts[4]
        if rng in bot_settings["stex_services"].get(srv, {}).get(cnt, []):
            bot_settings["stex_services"][srv][cnt].remove(rng)
            save_db()
            answer_callback(call["id"], f"✅ Range {rng} deleted!", show_alert=True)
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"nx_cnt_{srv}_{cnt}", "id": call["id"]})

    elif data.startswith("nx_del_srv_"):
        srv = data.replace("nx_del_srv_", "")
        if srv in bot_settings["stex_services"]: del bot_settings["stex_services"][srv]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_stex_srv", "id": call["id"]})

    elif data.startswith("nx_del_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[3], parts[4]
        if cnt in bot_settings["stex_services"].get(srv, {}): del bot_settings["stex_services"][srv][cnt]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"nx_srv_{srv}", "id": call["id"]})

    elif data == "voltx_control":
        edit_message(chat_id, msg_id, render_body_text(f"⚡ <b>Voltx Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('voltx_keys', []))}\nManage your Voltx API Keys below:"), reply_markup=voltx_control_keyboard())

    elif data == "toggle_voltx_auto":
        bot_settings["voltx_auto"] = not bot_settings.get("voltx_auto", False)
        save_db()
        edit_message(chat_id, msg_id, render_body_text(f"⚡ <b>Voltx Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('voltx_keys', []))}\nManage your Voltx API Keys below:"), reply_markup=voltx_control_keyboard())
        answer_callback(call["id"], f"✅ Voltx Auto Range is now {'ON' if bot_settings['voltx_auto'] else 'OFF'}!", show_alert=False)

    elif data == "add_voltx_key":
        user_states[chat_id] = "wait_for_add_voltx_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new Voltx API Key:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "danger"}]]})

    elif data == "view_voltx_keys":
        kb = []
        for idx, key in enumerate(bot_settings.get("voltx_keys", [])):
            safe_name = key[:10] + "..." if len(key)>10 else key
            kb.append([{"text": f"Delete {safe_name}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_vtx_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🗑 <b>Select Voltx Key to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_vtx_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("voltx_keys", [])):
            del bot_settings["voltx_keys"][idx]
            save_db()
            answer_callback(call["id"], "✅ Voltx Key Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "view_voltx_keys", "id": call["id"]})

    elif data == "voltx_search_country":
        kb = []
        for idx, c in enumerate(bot_settings.get("voltx_search_countries", [])):
            kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_vsc_{idx}", "style": "danger"}])
        kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_voltx_search_country", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🌍 <b>Voltx Allowed Ranges:</b>\nOnly these ranges/codes will be allowed in Voltx Search Number."), reply_markup={"inline_keyboard": kb})

    elif data == "add_voltx_search_country":
        user_states[chat_id] = "wait_for_add_vsc"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Voltx Range Code (e.g. 26134):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_search_country", "style": "danger"}]]})

    elif data.startswith("del_vsc_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("voltx_search_countries", [])):
            del bot_settings["voltx_search_countries"][idx]
            save_db()
            answer_callback(call["id"], "✅ Voltx Range Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "voltx_search_country", "id": call["id"]})

    elif data == "manage_voltx_srv":
        kb = []
        srvs = bot_settings.get("voltx_services", {})
        apps_db = bot_settings.get("premium_apps", {})
        for srv in srvs:
            emoji_id = "5257969839313526622"
            for app_key, app_data in apps_db.items():
                if srv.upper() == app_key or srv.upper() in app_key or app_key in srv.upper():
                    if "id" in app_data: emoji_id = app_data["id"]; break
            kb.append([{"text": f"{srv}", "icon_custom_emoji_id": emoji_id, "callback_data": f"vx_srv_{srv}", "style": "primary"}])
        kb.append([{"text": "Add New Service", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "vx_add_srv", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "danger"}])
        edit_message(chat_id, msg_id, render_body_text("⚡ <b>Voltx Services Manager</b>\nManage your API-based dynamic services below:"), reply_markup={"inline_keyboard": kb})

    elif data == "vx_add_srv":
        user_states[chat_id] = "wait_vx_srv_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Enter Service Name (e.g. TELEGRAM):"), reply_markup=get_cancel_kb())

    elif data.startswith("vx_srv_"):
        srv = data.replace("vx_srv_", "")
        kb = []
        countries = bot_settings["voltx_services"].get(srv, {})
        flags_db = bot_settings.get("premium_flags", {})
        for c in countries:
            emoji_id = "5780471598922337683"
            for flag_code, flag_data in flags_db.items():
                iso = flag_data.get("iso", "").upper()
                name = flag_data.get("name", "").upper()
                if c.upper() == iso or c.upper() == name or c.upper() in name or name in c.upper():
                    if "id" in flag_data: emoji_id = flag_data["id"]; break
            kb.append([{"text": f"{c} ({len(countries[c])} Ranges)", "icon_custom_emoji_id": emoji_id, "callback_data": f"vx_cnt_{srv}_{c}", "style": "primary"}])
        kb.append([{"text": "Add Country", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"vx_add_cnt_{srv}", "style": "success"}])
        kb.append([{"text": "Delete Service", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"vx_del_srv_{srv}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_voltx_srv", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📂 <b>Service: {srv}</b>\nManage countries for this service:"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("vx_add_cnt_"):
        srv = data.replace("vx_add_cnt_", "")
        user_states[chat_id] = "wait_vx_cnt_name"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv}
        edit_message(chat_id, msg_id, render_body_text(f"🌍 Enter Country Name for <b>{srv}</b> (e.g. BD, INDIA):"), reply_markup=get_cancel_kb())

    elif data.startswith("vx_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        ranges = bot_settings["voltx_services"][srv].get(cnt, [])
        kb = []
        row = []
        for r in ranges:
            row.append({"text": f"Delete {r}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"vx_dr_{srv}_{cnt}_{r}", "style": "danger"})
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)
        kb.append([{"text": "Add Range", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"vx_addr_{srv}_{cnt}", "style": "success"}])
        kb.append([{"text": "Delete Entire Country", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"vx_del_cnt_{srv}_{cnt}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"vx_srv_{srv}", "style": "primary"}])
        txt = f"📍 <b>Service: {srv} | Country: {cnt}</b>\n\n<b>Total Ranges:</b> {len(ranges)}\n<i>Click on a range below to delete it, or add a new one.</i>"
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("vx_addr_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        user_states[chat_id] = "wait_vx_addr"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv, "cnt": cnt}
        edit_message(chat_id, msg_id, render_body_text(f"📝 Send the new Range for <b>{cnt}</b> (e.g. 26134):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"vx_cnt_{srv}_{cnt}", "style": "danger"}]]})

    elif data.startswith("vx_dr_"):
        parts = data.split("_")
        srv, cnt, rng = parts[2], parts[3], parts[4]
        if rng in bot_settings["voltx_services"].get(srv, {}).get(cnt, []):
            bot_settings["voltx_services"][srv][cnt].remove(rng)
            save_db()
            answer_callback(call["id"], f"✅ Range {rng} deleted!", show_alert=True)
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"vx_cnt_{srv}_{cnt}", "id": call["id"]})

    elif data.startswith("vx_del_srv_"):
        srv = data.replace("vx_del_srv_", "")
        if srv in bot_settings["voltx_services"]: del bot_settings["voltx_services"][srv]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_voltx_srv", "id": call["id"]})

    elif data.startswith("vx_del_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[3], parts[4]
        if cnt in bot_settings["voltx_services"].get(srv, {}): del bot_settings["voltx_services"][srv][cnt]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"vx_srv_{srv}", "id": call["id"]})

    elif data == "zenex_control":
        edit_message(chat_id, msg_id, render_body_text(f"💠 <b>Zenex Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('zenex_keys', []))}\nManage your Zenex API Keys below:"), reply_markup=zenex_control_keyboard())

    elif data == "toggle_zenex_auto":
        bot_settings["zenex_auto"] = not bot_settings.get("zenex_auto", False)
        save_db()
        edit_message(chat_id, msg_id, render_body_text(f"💠 <b>Zenex Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('zenex_keys', []))}\nManage your Zenex API Keys below:"), reply_markup=zenex_control_keyboard())
        answer_callback(call["id"], f"✅ Zenex Auto Range is now {'ON' if bot_settings['zenex_auto'] else 'OFF'}!", show_alert=False)

    elif data == "add_zenex_key":
        user_states[chat_id] = "wait_for_add_zenex_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new Zenex API Key:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "zenex_control", "style": "danger"}]]})

    elif data == "view_zenex_keys":
        kb = []
        for idx, key in enumerate(bot_settings.get("zenex_keys", [])):
            safe_name = key[:10] + "..." if len(key)>10 else key
            kb.append([{"text": f"Delete {safe_name}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_znx_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "zenex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🗑 <b>Select Zenex Key to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_znx_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("zenex_keys", [])):
            del bot_settings["zenex_keys"][idx]
            save_db()
            answer_callback(call["id"], "✅ Zenex Key Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "view_zenex_keys", "id": call["id"]})

    elif data == "zenex_search_country":
        kb = []
        for idx, c in enumerate(bot_settings.get("zenex_search_countries", [])):
            kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_zsc_{idx}", "style": "danger"}])
        kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_zenex_search_country", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "zenex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🌍 <b>Zenex Allowed Ranges:</b>\nOnly these codes will be allowed in Zenex Search Number."), reply_markup={"inline_keyboard": kb})

    elif data == "add_zenex_search_country":
        user_states[chat_id] = "wait_for_add_zsc"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Zenex Range Code (e.g. 447):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "zenex_search_country", "style": "danger"}]]})

    elif data.startswith("del_zsc_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("zenex_search_countries", [])):
            del bot_settings["zenex_search_countries"][idx]
            save_db()
            answer_callback(call["id"], "✅ Zenex Range Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "zenex_search_country", "id": call["id"]})

    elif data == "manage_zenex_srv":
        kb = []
        for srv in bot_settings.get("zenex_services", {}):
            kb.append([{"text": f"{srv}", "icon_custom_emoji_id": "5257969839313526622", "callback_data": f"zx_srv_{srv}", "style": "primary"}])
        kb.append([{"text": "Add New Service", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "zx_add_srv", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "zenex_control", "style": "danger"}])
        edit_message(chat_id, msg_id, render_body_text("💠 <b>Zenex Services Manager</b>\nManage your API-based manual services below:"), reply_markup={"inline_keyboard": kb})

    elif data == "zx_add_srv":
        user_states[chat_id] = "wait_zx_srv_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Enter Service Name (e.g. TELEGRAM):"), reply_markup=get_cancel_kb())

    elif data.startswith("zx_srv_"):
        srv = data.replace("zx_srv_", "")
        kb = []
        for c in bot_settings.get("zenex_services", {}).get(srv, {}):
            kb.append([{"text": f"{c} ({len(bot_settings['zenex_services'][srv][c])} Ranges)", "icon_custom_emoji_id": "5780471598922337683", "callback_data": f"zx_cnt_{srv}_{c}", "style": "primary"}])
        kb.append([{"text": "Add Country", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"zx_add_cnt_{srv}", "style": "success"}])
        kb.append([{"text": "Delete Service", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"zx_del_srv_{srv}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_zenex_srv", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📂 <b>Service: {srv}</b>\nManage countries for this service:"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("zx_add_cnt_"):
        srv = data.replace("zx_add_cnt_", "")
        user_states[chat_id] = "wait_zx_cnt_name"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv}
        edit_message(chat_id, msg_id, render_body_text(f"🌍 Enter Country Name for <b>{srv}</b> (e.g. UK, USA):"), reply_markup=get_cancel_kb())

    elif data.startswith("zx_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        ranges = bot_settings["zenex_services"][srv].get(cnt, [])
        kb, row = [], []
        for r in ranges:
            row.append({"text": f"Delete {r}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"zx_dr_{srv}_{cnt}_{r}", "style": "danger"})
            if len(row) == 2: kb.append(row); row = []
        if row: kb.append(row)
        kb.append([{"text": "Add Range", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"zx_addr_{srv}_{cnt}", "style": "success"}])
        kb.append([{"text": "Delete Entire Country", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"zx_del_cnt_{srv}_{cnt}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"zx_srv_{srv}", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📍 <b>Service: {srv} | Country: {cnt}</b>\n\n<b>Total Ranges:</b> {len(ranges)}"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("zx_addr_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        user_states[chat_id] = "wait_zx_addr"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv, "cnt": cnt}
        edit_message(chat_id, msg_id, render_body_text(f"📝 Send the new Range for <b>{cnt}</b> (e.g. 4473845XXX):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"zx_cnt_{srv}_{cnt}", "style": "danger"}]]})

    elif data.startswith("zx_dr_"):
        parts = data.split("_")
        srv, cnt, rng = parts[2], parts[3], parts[4]
        if rng in bot_settings["zenex_services"].get(srv, {}).get(cnt, []):
            bot_settings["zenex_services"][srv][cnt].remove(rng)
            save_db()
            answer_callback(call["id"], f"✅ Range {rng} deleted!", show_alert=True)
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"zx_cnt_{srv}_{cnt}", "id": call["id"]})

    elif data.startswith("zx_del_srv_"):
        srv = data.replace("zx_del_srv_", "")
        if srv in bot_settings["zenex_services"]: del bot_settings["zenex_services"][srv]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_zenex_srv", "id": call["id"]})

    elif data.startswith("zx_del_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[3], parts[4]
        if cnt in bot_settings["zenex_services"].get(srv, {}): del bot_settings["zenex_services"][srv][cnt]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"zx_srv_{srv}", "id": call["id"]})

    elif data == "manage_fj":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "toggle_fj":
        bot_settings["fj_on"] = not bot_settings["fj_on"]
        save_db()
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "add_fj":
        user_states[chat_id] = "wait_for_add_fj"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send Channel Username or Invite Link:\n<i>(Note: For private channels, use the numeric ID like -100...)</i>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_fj", "style": "danger"}]]})

    elif data.startswith("del_fj_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fj_channels"]):
            del bot_settings["fj_channels"][idx]
            save_db()
            answer_callback(call["id"], "✅ Channel deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "manage_admins":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['user']} <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())

    elif data == "add_adm":
        user_states[chat_id] = "wait_for_add_adm"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID of the new Admin:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_admins", "style": "danger"}]]})

    elif data.startswith("del_adm_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["admins"]):
            del bot_settings["admins"][idx]
            save_db()
            answer_callback(call["id"], "✅ Admin deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['user']} <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())

    elif data == "manage_otp_groups":
        edit_message(chat_id, msg_id, render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())

    elif data == "add_fw":
        user_states[chat_id] = "wait_for_add_fw_id"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Group ID/Username to forward messages to:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "danger"}]]})

    elif data.startswith("manage_fw_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            grp_id = bot_settings["fw_groups"][idx]["chat_id"]
            edit_message(chat_id, msg_id, render_body_text(f"🛡 <b>Manage Group:</b> {grp_id}"), reply_markup=specific_fw_group_keyboard(idx))

    elif data.startswith("add_fwbtn_"):
        idx = int(data.split("_")[2])
        user_states[chat_id] = "wait_for_add_fw_btn"
        temp_data[chat_id] = {"msg_id": msg_id, "fw_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send Custom Inline Button format:\n<code>Button Text - https://link.com</code>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_fw_{idx}", "style": "danger"}]]})

    elif data.startswith("del_fwbtn_"):
        parts = data.split("_")
        idx, b_idx = int(parts[2]), int(parts[3])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            if 0 <= b_idx < len(bot_settings["fw_groups"][idx]["buttons"]):
                del bot_settings["fw_groups"][idx]["buttons"][b_idx]
                save_db()
                answer_callback(call["id"], "✅ Button deleted!", show_alert=True)
                edit_message(chat_id, msg_id, render_body_text(f"🛡 <b>Manage Group:</b> {bot_settings['fw_groups'][idx]['chat_id']}"), reply_markup=specific_fw_group_keyboard(idx))

    elif data.startswith("del_fw_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            del bot_settings["fw_groups"][idx]
            save_db()
            answer_callback(call["id"], "✅ Group deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())

    elif data == "edit_otp_link":
        user_states[chat_id] = "wait_for_otp_link"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new OTP Group Link:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "danger"}]]})

    elif data == "manage_panels":
        api_count = len([p for p in bot_settings["panels"] if p.get("type") == "API Panel"])
        cpt_count = len([p for p in bot_settings["panels"] if p.get("type", "API Panel") == "Auto Captcha Panel"])
        text = f"{PEM['gear']} <b>Panel Management</b>\n\nSelect which type of panel system you want to manage:"
        kb = {"inline_keyboard": [
            [{"text": f"Manage API Panels ({api_count})", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "manage_api_panels", "style": "primary"}],
            [{"text": f"Manage Auto Captcha Panels ({cpt_count})", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "manage_cpt_panels", "style": "success"}],
            [{"text": "Back to System", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
        ]}
        edit_message(chat_id, msg_id, render_body_text(text), reply_markup=kb)

    elif data in ["manage_api_panels", "manage_cpt_panels"]:
        p_type = "API Panel" if data == "manage_api_panels" else "Auto Captcha Panel"
        p_list = [p for p in bot_settings["panels"] if p.get("type", "API Panel") == p_type]
        icon = f"{PEM['world']} API" if p_type == 'API Panel' else f"{PEM['lock']} Auto Captcha"
        
        text = f"{icon} <b>{p_type}s Management</b>\n\n👀 <b>Active Monitors:</b> {len(p_list)}\n\n🟢 <b>Available Providers:</b>\n"
        for p in p_list:
            status = "Monitoring" if p['status'] == 'ON' else "Stopped"
            login_state = p.get('login_status', '')
            if p['type'] == 'Auto Captcha Panel':
                conf = f" {login_state}" if login_state else f"{PEM['ok']} Configured"
            else:
                conf = (
                    f"{PEM['ok']} Configured"
                    if p.get('api_url') or p.get('full_api_url')
                    else f"{PEM['no']} Not Configured"
                )
            text += f"• {p['name']}: {PEM['ok'] if p['status']=='ON' else PEM['no']} {status} | {conf}\n"
        edit_message(chat_id, msg_id, render_body_text(text), reply_markup=typed_panels_list_keyboard(p_type))

    elif data in ["add_api_panel", "add_cpt_panel"]:
        user_states[chat_id] = "wait_for_panel_name"
        p_type = "api" if data == "add_api_panel" else "logc"
        temp_data[chat_id] = {"msg_id": msg_id, "add_type": p_type}
        edit_message(chat_id, msg_id, render_body_text("📝 Please send the name of the New Provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_{'api' if p_type=='api' else 'cpt'}_panels", "style": "danger"}]]})

    elif data in ["list_del_api", "list_del_cpt"]:
        p_type = "API Panel" if data == "list_del_api" else "Auto Captcha Panel"
        kb = []
        for idx, p in enumerate(bot_settings["panels"]):
            if p.get("type", "API Panel") == p_type:
                kb.append([{"text": f"Delete {p['name']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"do_del_pnl_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_{'api' if p_type=='API Panel' else 'cpt'}_panels", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['trash']} <b>Select a Provider to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("do_del_pnl_"):
        idx = int(data.split("_")[3])
        if 0 <= idx < len(bot_settings["panels"]):
            p_type = bot_settings["panels"][idx].get("type", "API Panel")
            del bot_settings["panels"][idx]
            save_db()
            answer_callback(call["id"], "✅ Provider Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"manage_{'api' if p_type=='API Panel' else 'cpt'}_panels", "id": "internal"})

    elif data.startswith("tog_pnl_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["panels"]):
            p = bot_settings["panels"][idx]
            
            p["status"] = "ON" if p["status"] == "OFF" else "OFF"
            save_db()
            
            if p["type"] == "Auto Captcha Panel":
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>Login Status:</b> {p.get('login_status', 'Unknown')}\n<b>Login URL:</b> <code>{p.get('login_url', 'None')}</code>\n<b>User:</b> <code>{p.get('username', 'None')}</code>"
            else:
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, msg_id, render_body_text(text), reply_markup=panel_config_keyboard(idx))

    elif data.startswith("conf_pnl_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["panels"]):
            p = bot_settings["panels"][idx]
            if p["type"] == "Auto Captcha Panel":
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>Login Status:</b> {p.get('login_status', 'Unknown')}\n<b>Login URL:</b> <code>{p.get('login_url', 'None')}</code>\n<b>User:</b> <code>{p.get('username', 'None')}</code>\n<b>Num Col:</b> {p.get('num_col_name')} (Idx: {p.get('num_col_idx')})\n<b>Msg Col:</b> {p.get('msg_col_name')} (Idx: {p.get('msg_col_idx')})"
            else:
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>\n<b>Full API URL:</b> <code>{p.get('full_api_url', 'None')}</code>"
            edit_message(chat_id, msg_id, render_body_text(text), reply_markup=panel_config_keyboard(idx))

    elif data.startswith("set_p_api_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_api"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the API URL for this provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_tok_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_tok"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Token for this provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_fapi_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_fapi"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the FULL API URL (Example: http://api.com/get?key=YOUR_TOKEN&start=0):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_rec_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_rec"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the number of records to fetch (e.g. 10).\nType <code>0</code> for Unlimited:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("test_p_conn_"):
        idx = int(data.split("_")[3])
        if idx < 0 or idx >= len(bot_settings.get("panels", [])):
            answer_callback(call["id"], "❌ Provider no longer exists.", show_alert=True)
            return
        p = bot_settings["panels"][idx]
        wait_msg = send_message(
            chat_id,
            render_body_text(loading_html("Testing connection. Please wait..."))
        )
        wait_msg_id = wait_msg.get("result", {}).get("message_id") if wait_msg else None
        answer_callback(call["id"])
        
        try:
            parsed = []
            raw_text = ""
            number_rows = []
            api_status = "OK"
            
            if p["type"] == "Auto Captcha Panel":
                sess = panel_sessions.get(idx)
                if not sess:
                    success = attempt_auto_login(p, idx)
                    if not success:
                        if wait_msg_id: delete_message(chat_id, wait_msg_id)
                        send_message(chat_id, render_body_text(f"❌ <b>Auto Login Failed!</b>\nReason: {html.escape(str(p.get('login_status', 'Unknown')))}"))
                        return
                    sess = panel_sessions.get(idx)
                    
                login_url = p.get("login_url", "").strip()
                if not login_url.startswith("http"): login_url = "http://" + login_url
                msg_link = p.get("msg_link", "").strip()
                if not msg_link.startswith("http") and msg_link != "": msg_link = "http://" + msg_link
                check_url = msg_link if msg_link else f"{login_url.split('/login')[0]}/client/SMSCDRStats"
                
                parsed, raw_text = fetch_cpt_panel_cdrs(p, sess, check_url)
                
            else:
                parsed, number_rows, api_status = fetch_api_panel_data(p, timeout=15)
                 
            if wait_msg_id: delete_message(chat_id, wait_msg_id)
                 
            if parsed:
                txt = f"✅ <b>Connection Successful!</b>\n<b>Status:</b> {html.escape(str(api_status))}\n\n🎯 <b>Parsed Data Sample (Max 3):</b>\n\n"
                
                for i, sample in enumerate(parsed[:3]):
                    num = sample['number']
                    msg = sample['message']
                    otp = sample['otp']
                    
                    detected_app = detect_service(msg)
                    app_name = detected_app if detected_app else p.get("name", "Unknown")
                    app_full_name, prem_app_html = get_service_info_html(app_name, msg)
                    
                    txt += f"<b>{i+1}.</b> {prem_app_html} <b>{app_full_name}</b>\n"
                    txt += f"📱 Number: <code>{num}</code>\n"
                    txt += f"📝 Full Msg: <code>{html.escape(msg)}</code>\n"
                    txt += f"🔐 OTP: <code>{otp}</code>\n"
                    txt += "➖" * 12 + "\n"
                    
                send_message(chat_id, render_body_text(txt))
            elif p["type"] != "Auto Captcha Panel" and number_rows:
                txt = (
                    f"✅ <b>Connection Successful!</b>\n"
                    f"<b>Status:</b> {html.escape(str(api_status))}\n\n"
                    f"📱 <b>Real number records found:</b> {len(number_rows)}\n\n"
                )
                for i, sample in enumerate(number_rows[:5], 1):
                    service = sample.get("service") or p.get("name", "Provider")
                    message_state = "SMS message found" if sample.get("message") else "Number available"
                    txt += (
                        f"<b>{i}.</b> {html.escape(str(service))}\n"
                        f"📱 Number: <code>+{html.escape(str(sample['number']))}</code>\n"
                        f"📌 {message_state}\n"
                    )
                send_message(chat_id, render_body_text(txt))
            elif p["type"] != "Auto Captcha Panel" and re.match(r"^HTTP 2\d\d\b", str(api_status)):
                # A provider can legitimately return an empty list when its
                # stock is empty. That still proves that the URL and
                # transport/authentication worked, so do not call it a
                # connection failure.
                send_message(
                    chat_id,
                    render_body_text(
                        "✅ <b>Connected Successfully</b>\n\n"
                        f"<b>Status:</b> {html.escape(str(api_status))}\n"
                        "📱 <b>Real number records:</b> 0\n\n"
                        "Panel connected, but this response currently contains "
                        "no available real number/OTP. No fake number was added."
                    ),
                )
            else:
                if p["type"] == "Auto Captcha Panel":
                    try:
                        soup = BeautifulSoup(raw_text, 'html.parser')
                        tables = soup.find_all('table')
                        if tables:
                            full_table_data = "🔍 FULL TABLE DATA (A-Z)\n" + "="*50 + "\n\n"
                            for t_idx, table in enumerate(tables):
                                full_table_data += f"--- Table {t_idx+1} ---\n"
                                rows = table.find_all('tr')
                                for r_idx, row in enumerate(rows):
                                    cols = row.find_all(['th', 'td'])
                                    col_texts = [f"[{c_idx+1}] {c.get_text(separator=' ', strip=True)}" for c_idx, c in enumerate(cols)]
                                    full_table_data += f"Row {r_idx+1}: {' | '.join(col_texts)}\n"
                                full_table_data += "\n" + "="*50 + "\n"
                            
                            send_document(chat_id, f"Full_Panel_Data_{idx}.txt", full_table_data.encode('utf-8'))
                            fail_txt = f"⚠️ <b>Connected, but couldn't parse OTP data!</b>\n\n<i>আমি ওই লিংকের সম্পূর্ণ (A-Z) ডাটা একটি Text File এ পাঠিয়েছি। ফাইলটি ওপেন করে সঠিক Column Number (যেমন: [1], [3]) চেক করে প্যানেলে আপডেট করে নাও।</i>"
                            send_message(chat_id, render_body_text(fail_txt))
                        else:
                            send_message(chat_id, render_body_text(f"⚠️ <b>Connected, but no HTML Table found!</b>\nMake sure the message link is correct."))
                    except Exception as e:
                        send_message(chat_id, render_body_text(f"❌ <b>Error parsing HTML:</b> {html.escape(str(e))}"))
                else:
                    p["last_api_error"] = api_status
                    save_db()
                    send_message(
                        chat_id,
                        render_body_text(
                            "⚠️ <b>Request completed, but no real number or OTP record was recognized.</b>\n\n"
                            f"<b>Provider response:</b> <code>{html.escape(str(api_status))}</code>\n\n"
                            "URL সেভ হয়েছে। Hadi API যদি অন্য field name/response format দেয়, "
                            "তার raw JSON format অনুযায়ী parser mapping লাগবে—কোনো fake number দেখানো হবে না।"
                        ),
                    )
        except Exception as e:
            if wait_msg_id: delete_message(chat_id, wait_msg_id)
            send_message(chat_id, render_body_text(f"❌ <b>Connection Failed!</b>\nError: {html.escape(str(e))}"))

    elif data == "GX_control":
        if chat_id in user_states: del user_states[chat_id]
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>GX CONTROL PANEL</b>"), reply_markup=GX_control_keyboard())

    elif data == "GX_toggle_w":
        bot_settings["withdraw_on"] = not bot_settings["withdraw_on"]
        save_db()
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>GX CONTROL PANEL</b>"), reply_markup=GX_control_keyboard())

    elif data == "manage_w_methods":
        edit_message(chat_id, msg_id, render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())

    elif data == "add_wm":
        user_states[chat_id] = "wait_for_add_wm"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the name of the new Withdrawal Method:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_w_methods", "style": "danger"}]]})

    elif data.startswith("del_wm_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["w_methods"]):
            del bot_settings["w_methods"][idx]
            save_db()
            answer_callback(call["id"], "✅ Method deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())

    elif data.startswith("GX_"):
        key = data.replace("GX_", "")
        key_map = {"min_w": "min_withdraw", "otp_r": "otp_reward", "ref_r": "refer_reward", "cool": "cooldown", "num_req": "num_req", "num_share": "num_share", "sup_link": "support_link", "w_group": "w_group"}
        if key in key_map:
            temp_data[chat_id] = {"msg_id": msg_id, "key": key_map[key]}
            user_states[chat_id] = "set_GX"
            cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_GX_edit", "style": "danger"}]]}
            edit_message(chat_id, msg_id, render_body_text(f"📝 Please send the new value for <code>{key_map[key]}</code>:"), reply_markup=cancel_kb)
            answer_callback(call["id"])

    elif data == "back_to_services":
        local_srvs = set([b["service"] for b in number_batches.values() if b["numbers"]])
        stex_srvs = set(bot_settings.get("stex_services", {}).keys())
        voltx_srvs = set(bot_settings.get("voltx_services", {}).keys())
        zenex_srvs = set(bot_settings.get("zenex_services", {}).keys())
        all_services = local_srvs.union(stex_srvs).union(voltx_srvs).union(zenex_srvs)
        
        if not all_services:
            answer_callback(call["id"], "❌ No numbers or services available!", show_alert=True)
            return
            
        c_msg = bot_settings["custom_messages"].get("get_number", {})
        txt = render_body_text(c_msg.get("text", f"{PEM['pin']} Select Service"))
        
        apps_db = bot_settings.get("premium_apps", {})
        kb = []
        service_buttons = []
        for s in sorted(
            all_services,
            key=lambda value: (-_service_traffic_count(value), str(value).lower()),
        ):
            emoji_id = "5352694861990501856" 
            for app_key, app_data in apps_db.items():
                if s.upper() == app_key or s.upper() in app_key or app_key in s.upper():
                    if "id" in app_data:
                        emoji_id = app_data["id"]
                        break
            service_name, _ = get_service_info_html(s)
            service_buttons.append(
                {
                    "text": service_name,
                    "icon_custom_emoji_id": emoji_id,
                    "callback_data": f"g_s_{s}",
                    "style": "primary",
                }
            )
        service_buttons = _equal_service_button_labels(service_buttons)
        txt = _stretch_service_prompt(txt, service_buttons)
        kb.extend(_two_column_rows(service_buttons))
        
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        
        edit_message(chat_id, msg_id, txt, reply_markup={"inline_keyboard": kb})

    elif data.startswith("g_s_"):
        service = data.split("g_s_")[1]
        local_cnts = set([b["country"] for b in number_batches.values() if b["service"] == service and b["numbers"]])
        stex_cnts = set(bot_settings.get("stex_services", {}).get(service, {}).keys())
        voltx_cnts = set(bot_settings.get("voltx_services", {}).get(service, {}).keys())
        zenex_cnts = set(bot_settings.get("zenex_services", {}).get(service, {}).keys())
        all_countries = local_cnts.union(stex_cnts).union(voltx_cnts).union(zenex_cnts)
        all_countries = _top_traffic_countries(service, all_countries, limit=7)
        
        c_msg = bot_settings["custom_messages"].get("select_country", {})
        raw_txt = c_msg.get("text", "📌 Select a country for {service}:").replace("{service}", service)
        txt = render_body_text(raw_txt)
        
        flags_db = bot_settings.get("premium_flags", {})
        kb = []
        country_buttons = []
        for c in all_countries:
            emoji_id = "5780471598922337683"
            for flag_code, flag_data in flags_db.items():
                iso = flag_data.get("iso", "").upper()
                name = flag_data.get("name", "").upper()
                if c.upper() == iso or c.upper() == name or c.upper() in name or name in c.upper():
                    if "id" in flag_data:
                        emoji_id = flag_data["id"]
                        break
            
            otp_price = bot_settings.get("otp_reward", 0.0)
            for b in number_batches.values():
                if b.get("service") == service and b.get("country") == c and "rate" in b and b.get("numbers"):
                    otp_price = b.get("rate")
                    break
                    
            country_buttons.append(
                {
                    "text": f"{c} - {otp_price} TK/OTP",
                    "icon_custom_emoji_id": emoji_id,
                    "callback_data": f"g_c_{service}_{c}",
                    "style": "success",
                }
            )
        kb.extend(_two_column_rows(country_buttons))
        
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
            
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_services", "style": "danger"}])
        edit_message(chat_id, msg_id, txt, reply_markup={"inline_keyboard": kb})

    elif data.startswith("g_c_") or data.startswith("c_n_"):
        now = time.time()
        if now - user_cooldowns.get(chat_id, 0) < bot_settings["cooldown"]:
            answer_callback(call["id"], f"⌛ Please wait {int(bot_settings['cooldown'] - (now - user_cooldowns.get(chat_id, 0)))}s.", show_alert=True)
            return
        
        user_cooldowns[chat_id] = now
        expire_previous_number(chat_id)

        if data.startswith("c_n_s_"):
            is_voltx_req = data.endswith("_vtx")
            is_zenex_req = data.endswith("_znx")
            clean_data = data[:-4] if (is_voltx_req or is_zenex_req) else data
            parts_s = clean_data.split("_", 4)
            
            query = parts_s[3] if len(parts_s) > 3 else ""
            service_from_cb = parts_s[4] if len(parts_s) > 4 else None
            
            allowed_countries = bot_settings.get("search_countries", [])
            voltx_allowed = bot_settings.get("voltx_search_countries", [])
            zenex_allowed = bot_settings.get("zenex_search_countries", [])
            
            is_stex_allowed = any(query.startswith(c) for c in allowed_countries) if allowed_countries else False
            is_voltx_allowed = any(query.startswith(c) for c in voltx_allowed) if voltx_allowed else False
            is_zenex_allowed = any(query.startswith(c) for c in zenex_allowed) if zenex_allowed else False
            
            if not is_stex_allowed and not is_voltx_allowed and not is_zenex_allowed:
                answer_callback(call["id"], "❌ This country code is not allowed for search!", show_alert=True)
                return
                
            # Country selection uses two visible loading stages:
            # Both loading messages start together and are removed together.
            delete_message(chat_id, msg_id)
            fetching_msg_id, fetching_started_at = start_fetching_loading(chat_id)
            reveal_msg_id, reveal_started_at = start_premium_reveal(chat_id)
            
            fetched_nums, source = fetch_numbers_fast(
                query,
                chat_id,
                requested_number_count(),
                source_hint="voltx" if is_voltx_req else "zenex" if is_zenex_req else None,
            )
            finish_combined_loading(
                chat_id,
                fetching_msg_id,
                reveal_msg_id,
                reveal_started_at
            )
            
            if not fetched_nums:
                answer_callback(call["id"], "❌ Number out of stock!", show_alert=True)
                return

            kb = []
            if service_from_cb:
                app_full_name, _ = get_service_info_html(service_from_cb)
                emoji_id_srv = "5337302974806922068"
                for app_key, app_data in bot_settings.get("premium_apps", {}).items():
                    if service_from_cb.upper() == app_key or service_from_cb.upper() in app_key or app_key in service_from_cb.upper():
                        if "id" in app_data: emoji_id_srv = app_data["id"]; break
                kb.append([{"text": f"{app_full_name}", "icon_custom_emoji_id": emoji_id_srv, "callback_data": "ignore", "style": "primary"}])

            flags_db = bot_settings.get("premium_flags", {})
            country_emoji_html = ""
            display_nums = []
            for num in fetched_nums:
                char_flag, iso = get_flag_and_code(num)
                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                display_nums.append(display_num)
                flag_emoji_id = "5780471598922337683"
                for flag_code, flag_data in flags_db.items():
                    if iso == flag_data.get("iso"):
                        if "id" in flag_data: 
                            flag_emoji_id = flag_data["id"]
                            country_emoji_html = f'<tg-emoji emoji-id="{flag_emoji_id}">{flag_data["char"]}</tg-emoji>'
                        break
                if not country_emoji_html: country_emoji_html = char_flag
                kb.append([{
                    "text": _compact_number_label(display_num),
                    "icon_custom_emoji_id": flag_emoji_id,
                    "copy_text": {"text": display_num},
                    "style": "success",
                }])
            
            vtx_ext = "_vtx" if is_voltx_req else "_znx" if is_zenex_req else ""
            srv_ext = f"_{service_from_cb}" if service_from_cb else ""
            action_row = [{
                "text": "Change Number",
                "icon_custom_emoji_id": "5465368548702446780",
                "callback_data": f"c_n_s_{query}{srv_ext}{vtx_ext}",
                "style": "danger",
            }]
            if service_from_cb:
                action_row.append({
                    "text": "Change Country",
                    "icon_custom_emoji_id": "5305517382138112561",
                    "callback_data": f"g_s_{service_from_cb}",
                    "style": "danger",
                })
            kb.append(action_row)
            kb.append([{"text": "OTP Group", "icon_custom_emoji_id": "5190447043545438788", "url": bot_settings["otp_link"], "style": "primary"}])
            
            success_mark = f'<tg-emoji emoji-id="{NUMBER_SUCCESS_EMOJI_ID}">✅</tg-emoji>'
            text_numbers = render_body_text(
                f"{success_mark} <b>NUMBER GENERATED SUCCESSFULLY</b>"
            )
            msg_res = send_message(
                chat_id, text_numbers, reply_markup={"inline_keyboard": kb}
            )
            if msg_res and "result" in msg_res:
                user_active_sessions[chat_id] = {
                    "msg_id": msg_res["result"]["message_id"],
                    "nums": fetched_nums
                }
            return

        parts = data.split("_")
        service = parts[2]
        country = parts[3]

        has_local_stock = any(
            b_data.get("service") == service
            and b_data.get("country") == country
            and any(
                chat_id not in item.get("used_by", [])
                and not _number_is_claimed(item.get("num"))
                for item in b_data.get("numbers", [])
                if isinstance(item, dict)
            )
            for b_data in number_batches.values()
        )

        if not has_local_stock:
            stex_srv_data = bot_settings.get("stex_services", {}).get(service, {}).get(country)
            voltx_srv_data = bot_settings.get("voltx_services", {}).get(service, {}).get(country)
            zenex_srv_data = bot_settings.get("zenex_services", {}).get(service, {}).get(country)
            
            target_range = None
            is_voltx = False
            is_zenex = False
            
            if stex_srv_data and len(stex_srv_data) > 0:
                target_range = random.choice(stex_srv_data)
            elif voltx_srv_data and len(voltx_srv_data) > 0:
                target_range = random.choice(voltx_srv_data)
                is_voltx = True
            elif zenex_srv_data and len(zenex_srv_data) > 0:
                target_range = random.choice(zenex_srv_data)
                is_zenex = True
                
            if target_range:
                user_cooldowns[chat_id] = 0
                vtx_flag = "_vtx" if is_voltx else "_znx" if is_zenex else ""
                handle_callback({"message": call["message"], "data": f"c_n_s_{target_range}_{service}{vtx_flag}", "id": call["id"]})
                return
            else:
                answer_callback(call["id"], "❌ Number out of stock or range missing!", show_alert=True)
                if data.startswith("c_n_"): delete_message(chat_id, msg_id)
                return

        # Local numbers use the same two-stage loading sequence as API numbers.
        delete_message(chat_id, msg_id)
        fetching_msg_id, fetching_started_at = start_fetching_loading(chat_id)
        reveal_msg_id, reveal_started_at = start_premium_reveal(chat_id)

        fetched_nums = _reserve_local_numbers(
            query="",
            chat_id=chat_id,
            req_count=requested_number_count(),
            service=service,
            country=country,
        )

        if not fetched_nums:
            finish_combined_loading(
                chat_id,
                fetching_msg_id,
                reveal_msg_id,
                reveal_started_at
            )
            answer_callback(call["id"], "❌ You have already taken all numbers or stock is empty!", show_alert=True)
            return

        finish_combined_loading(
            chat_id,
            fetching_msg_id,
            reveal_msg_id,
            reveal_started_at
        )

        app_full_name, _ = get_service_info_html(service)
        emoji_id = "5337302974806922068"
        apps_db = bot_settings.get("premium_apps", {})
        for app_key, app_data in apps_db.items():
            if service.upper() == app_key or service.upper() in app_key or app_key in service.upper():
                if "id" in app_data:
                    emoji_id = app_data["id"]
                    break
        kb = [[{"text": f"{app_full_name}", "icon_custom_emoji_id": emoji_id, "callback_data": "ignore", "style": "primary"}]]
        
        flags_db = bot_settings.get("premium_flags", {})
        country_emoji_html = ""
        display_nums = []
        for num in fetched_nums:
            char_flag, iso = get_flag_and_code(num)
            display_num = f"+{num}" if not num.startswith("+") else num
            display_nums.append(display_num)
            
            flag_emoji_id = "5780471598922337683"
            for flag_code, flag_data in flags_db.items():
                if iso == flag_data.get("iso"):
                    if "id" in flag_data: 
                        flag_emoji_id = flag_data["id"]
                        country_emoji_html = f'<tg-emoji emoji-id="{flag_emoji_id}">{flag_data["char"]}</tg-emoji>'
                    break
            
            if not country_emoji_html: country_emoji_html = char_flag
            kb.append([{
                "text": _compact_number_label(display_num),
                "icon_custom_emoji_id": flag_emoji_id,
                "copy_text": {"text": display_num},
                "style": "success",
            }])
            
        kb.append([
            {
                "text": "Change Number",
                "icon_custom_emoji_id": "5465368548702446780",
                "callback_data": f"c_n_{service}_{country}",
                "style": "danger",
            },
            {
                "text": "Change Country",
                "icon_custom_emoji_id": "5305517382138112561",
                "callback_data": f"g_s_{service}",
                "style": "danger",
            },
        ])

        c_btns = bot_settings["custom_messages"].get("get_number", {}).get("buttons", [])
        for c_b in c_btns: 
            b_copy = c_b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
            
        kb.append([{"text": "OTP Group", "icon_custom_emoji_id": "5190447043545438788", "url": bot_settings["otp_link"], "style": "primary"}])
        
        success_mark = f'<tg-emoji emoji-id="{NUMBER_SUCCESS_EMOJI_ID}">✅</tg-emoji>'
        text_numbers = render_body_text(
            f"{success_mark} <b>NUMBER GENERATED SUCCESSFULLY</b>"
        )
        msg_res = send_message(
            chat_id, text_numbers, reply_markup={"inline_keyboard": kb}
        )
        if msg_res and "result" in msg_res:
            user_active_sessions[chat_id] = {
                "msg_id": msg_res["result"]["message_id"],
                "nums": fetched_nums
            }

    elif data.startswith("wapp_") or data.startswith("wrej_"):
        user_id_clicked = call["from"]["id"]
        if not is_admin(user_id_clicked):
            answer_callback(call["id"], "🚫 Only Bot Admins can process withdrawals!", show_alert=True)
            return
            
        action = "APPROVE" if data.startswith("wapp_") else "REJECT"
        req_id = data.replace("wapp_", "").replace("wrej_", "")
        
        if req_id in pending_withdrawals:
            req_data = pending_withdrawals[req_id]
            u_id, amt = req_data["user_id"], req_data["amount"]
            num = req_data["number"]
            full_name = req_data.get("full_name", u_id)
            
            if action == "APPROVE" and len(num) >= 7:
                masked_num = f"{num[:4]}❖GX❖{num[-3:]}"
            else:
                masked_num = num
            
            status_text = "APPROVED" if action == "APPROVE" else "REJECTED"
            emoji_icon_id = "5352694861990501856" if action == "APPROVE" else "5420130255174145507"
            new_text = f"🎙 <b>WITHDRAWAL {status_text}</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={u_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amt} TK\n🍏 <b>NUMBER:</b> <code>{masked_num}</code>\n🏦 <b>METHOD:</b> {req_data['method']}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
            
            kb = {"inline_keyboard": [[{"text": status_text, "icon_custom_emoji_id": emoji_icon_id, "callback_data": "ignore", "style": "success" if action == "APPROVE" else "danger"}]]}
            edit_message(chat_id, msg_id, render_body_text(new_text), reply_markup=kb)
            
            if action == "REJECT":
                update_balance(u_id, amt, reason="withdrawal_refund") 
                send_message(u_id, render_body_text(f"❌ Your {amt} TK withdrawal request was rejected. Balance refunded."))
            else:
                send_message(u_id, render_body_text(f"{PEM['ok']} Your {amt} TK withdrawal request has been paid successfully!"))
            
            if db:
                try: db.collection('withdrawals').document(req_id).update({"status": "approved" if action == "APPROVE" else "rejected"})
                except: pass
            record_history(
                u_id,
                "withdrawal_status",
                message=f"Withdrawal {status_text.lower()}: {amt} TK via {req_data['method']}",
                amount=amt,
                status="approved" if action == "APPROVE" else "rejected",
                method=req_data["method"],
                request_id=req_id,
                payment_number=req_data.get("number", "")
            )
                
            del pending_withdrawals[req_id]
        else:
            answer_callback(call["id"], "❌ Request already processed!", show_alert=True)

# ==========================================
# Polling Loop
# ==========================================
def poll_otp_with_status(number_id, num_str, owner_id, api_key):
    headers = {"X-API-Key": api_key}
    for _ in range(150):
        try:
            res = requests.get(f"{STEX_BASE_URL}/api/v1/numbers/{number_id}/sms", headers=headers, timeout=10)
            data = res.json()
            if data.get("success") and data.get("otp"):
                otp = str(data["otp"])
                msg_text = data.get("message", f"Your code is {otp}")
                
                extracted_otp = extract_otp_code(msg_text)
                if extracted_otp and len(extracted_otp) > len(otp):
                    otp = extracted_otp
                    
                app_name = data.get("service", "StexSMS Service")
                detected_app = detect_service(msg_text)
                if detected_app:
                    app_name = detected_app
                
                unique_id = f"POLL_{number_id}_{otp}"
                if unique_id not in processed_otps:
                    processed_otps.add(unique_id)
                    
                    char, iso = get_flag_and_code(num_str)
                    app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                    
                    global recent_traffic
                    current_time = time.time()
                    recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                    recent_traffic.append({"service": app_full_name, "iso": iso, "flag": char, "number": num_str, "time": current_time})
                    save_local_db()
                    
                    display_num = f"+{num_str}" if not str(num_str).startswith("+") else str(num_str)
                    masked = mask_number(display_num)
                    lang = detect_language(msg_text)
                    
                    display_msg = render_body_text(f"╔═══════════════╗\n║ {prem_app_html} {get_flag_info_html(display_num)} {masked} {lang}\n╚═══════════════╝")
                    
                    for fw in bot_settings.get("fw_groups", []):
                        kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                        temp_row = []
                        styles = ["danger", "success", "primary"]
                        for i, btn in enumerate(fw.get("buttons", [])):
                            b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                            if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                            temp_row.append(b_obj)
                            if len(temp_row) == 2:
                                kb.append(temp_row)
                                temp_row = []
                        if temp_row: kb.append(temp_row)
                        send_message(fw["chat_id"], display_msg, reply_markup={"inline_keyboard": kb})
                    
                    inbox_msg = render_body_text(f"╔═══════════════╗\n║ {prem_app_html} {get_flag_info_html(display_num)} {display_num} {lang}\n╚═══════════════╝")
                    inbox_kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": otp}, "style": "success"}]]
                    
                    reward = float(assigned_number_rates.get(num_str, bot_settings.get("otp_reward", 0.0)))
                    if reward > 0:
                        update_balance(owner_id, reward)
                        inbox_kb.append([{"text": f"Added {reward} tk", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                    
                    send_message(owner_id, inbox_msg, reply_markup={"inline_keyboard": inbox_kb})
                    
                    record_user_otp(owner_id, otp)
                break
        except: pass
        time.sleep(4)

def stex_console_listener():
    global recent_traffic, bot_settings
    seen_console_hits = set()
    last_auto_update = time.time()
    
    while True:
        try:
            stex_keys = bot_settings.get("stex_keys", [])
            if stex_keys:
                api_key = stex_keys[0]
                headers = {"mauthapi": api_key}
                res = requests.get(f"{STEX_BASE_URL}/console", headers=headers, timeout=10)
                data = res.json()
                
                if data.get("meta", {}).get("code") == 200 and data.get("data", {}).get("hits"):
                    current_time = time.time()
                    new_hits = False
                    
                    for hit in data["data"]["hits"]:
                        range_str = str(hit.get("range", "")).replace("X", "")
                        if len(range_str) > 9:
                            range_str = range_str[:9]
                        sid = str(hit.get("sid", "Unknown"))
                        msg = str(hit.get("message", ""))
                        hit_time = hit.get("time", current_time * 1000) / 1000.0
                        
                        unique_hit = f"STEX_{range_str}_{sid}_{hit.get('time', 0)}"
                        if unique_hit not in seen_console_hits and range_str:
                            seen_console_hits.add(unique_hit)
                            if len(seen_console_hits) > 2000: seen_console_hits.clear()
                            
                            char, iso = get_flag_and_code(range_str)
                            app_full_name, _ = get_service_info_html(sid, msg)
                            
                            recent_traffic.append({
                                "service": app_full_name,
                                "iso": iso,
                                "flag": char,
                                "number": f"{range_str}XXX", 
                                "time": hit_time,
                                "real_range": range_str
                            })
                            new_hits = True
                            
                    if new_hits:
                        recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                        save_local_db()
                        
                    if bot_settings.get("stex_auto", False) and current_time - last_auto_update > 120:
                        last_auto_update = current_time
                        changed = False
                        
                        if "stex_services" not in bot_settings: bot_settings["stex_services"] = {}
                        if "search_countries" not in bot_settings: bot_settings["search_countries"] = []
                        
                        srv_counts = Counter(t["service"].upper() for t in recent_traffic if "real_range" in t)
                        top_srvs = [s for s, c in srv_counts.most_common(6)]
                        
                        for srv in top_srvs:
                            if srv not in bot_settings["stex_services"]:
                                bot_settings["stex_services"][srv] = {}
                                changed = True
                                
                            iso_counts = Counter(t["iso"] for t in recent_traffic if t.get("service", "").upper() == srv and "real_range" in t)
                            top_isos = [i for i, c in iso_counts.most_common(3)]
                            
                            for iso in top_isos:
                                full_country_name = get_flag_info_html(iso, return_full_name=True).title()
                                if full_country_name not in bot_settings["stex_services"][srv]:
                                    bot_settings["stex_services"][srv][full_country_name] = []
                                    changed = True
                                    
                                rng_counts = Counter(t["real_range"] for t in recent_traffic if t.get("service", "").upper() == srv and t.get("iso") == iso and "real_range" in t)
                                top_rngs = [r for r, c in rng_counts.most_common(2)]
                                
                                for rng in top_rngs:
                                    if rng not in bot_settings["stex_services"][srv][full_country_name]:
                                        bot_settings["stex_services"][srv][full_country_name].append(rng)
                                        changed = True
                                        
                                    country_code = rng[:3]
                                    if country_code not in bot_settings["search_countries"]:
                                        bot_settings["search_countries"].append(country_code)
                                        changed = True

                        services_to_remove = []
                        for srv, countries in list(bot_settings["stex_services"].items()):
                            srv_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and "real_range" in t and current_time - t.get("time", 0) <= 120)
                            if srv_hit < 1:
                                services_to_remove.append(srv)
                                continue
                            
                            countries_to_remove = []
                            for country, ranges in list(countries.items()):
                                c_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and get_flag_info_html(t.get("iso"), return_full_name=True).title() == country and "real_range" in t and current_time - t.get("time", 0) <= 120)
                                if c_hit < 1:
                                    countries_to_remove.append(country)
                                    continue
                                
                                ranges_to_remove = []
                                for rng in ranges:
                                    r_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and t.get("real_range") == rng and current_time - t.get("time", 0) <= 120)
                                    if r_hit < 1: 
                                        ranges_to_remove.append(rng)
                                
                                for r in ranges_to_remove:
                                    ranges.remove(r)
                                    changed = True
                                    
                            for c in countries_to_remove:
                                del bot_settings["stex_services"][srv][c]
                                changed = True
                                
                        for s in services_to_remove:
                            del bot_settings["stex_services"][s]
                            changed = True
                            
                        if changed:
                            save_db()
                            
        except Exception as e:
            pass
        time.sleep(10)

def voltx_console_listener():
    global recent_traffic, bot_settings
    seen_console_hits = set()
    last_auto_update = time.time()
    
    while True:
        try:
            if not bot_settings.get("voltx_on", True):
                time.sleep(5)
                continue
            voltx_keys = bot_settings.get("voltx_keys", [])
            if voltx_keys:
                api_key = voltx_keys[0]
                headers = {"mauthapi": api_key}
                res = requests.get(f"{VOLTX_BASE_URL}/console", headers=headers, timeout=10)
                data = res.json()
                
                if data.get("meta", {}).get("code") == 200 and data.get("data", {}).get("hits"):
                    current_time = time.time()
                    new_hits = False
                    
                    for hit in data["data"]["hits"]:
                        range_str = str(hit.get("range", "")).replace("X", "")
                        if len(range_str) > 9:
                            range_str = range_str[:9]
                        sid = str(hit.get("sid", "Unknown"))
                        msg = str(hit.get("message", ""))
                        hit_time = hit.get("time", current_time * 1000) / 1000.0
                        
                        unique_hit = f"{range_str}_{sid}_{hit.get('time', 0)}"
                        if unique_hit not in seen_console_hits and range_str:
                            seen_console_hits.add(unique_hit)
                            if len(seen_console_hits) > 2000: seen_console_hits.clear()
                            
                            char, iso = get_flag_and_code(range_str)
                            app_full_name, _ = get_service_info_html(sid, msg)
                            
                            recent_traffic.append({
                                "service": app_full_name,
                                "iso": iso,
                                "flag": char,
                                "number": f"{range_str}XXX", 
                                "time": hit_time,
                                "real_range": range_str
                            })
                            new_hits = True
                            
                    if new_hits:
                        recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                        save_local_db()
                        
                    if bot_settings.get("voltx_auto", False) and current_time - last_auto_update > 120:
                        last_auto_update = current_time
                        changed = False
                        
                        if "voltx_services" not in bot_settings: bot_settings["voltx_services"] = {}
                        if "voltx_search_countries" not in bot_settings: bot_settings["voltx_search_countries"] = []
                        
                        srv_counts = Counter(t["service"].upper() for t in recent_traffic if "real_range" in t)
                        top_srvs = [s for s, c in srv_counts.most_common(6)]
                        
                        for srv in top_srvs:
                            if srv not in bot_settings["voltx_services"]:
                                bot_settings["voltx_services"][srv] = {}
                                changed = True
                                
                            iso_counts = Counter(t["iso"] for t in recent_traffic if t.get("service", "").upper() == srv and "real_range" in t)
                            top_isos = [i for i, c in iso_counts.most_common(3)]
                            
                            for iso in top_isos:
                                full_country_name = get_flag_info_html(iso, return_full_name=True).title()
                                if full_country_name not in bot_settings["voltx_services"][srv]:
                                    bot_settings["voltx_services"][srv][full_country_name] = []
                                    changed = True
                                    
                                rng_counts = Counter(t["real_range"] for t in recent_traffic if t.get("service", "").upper() == srv and t.get("iso") == iso and "real_range" in t)
                                top_rngs = [r for r, c in rng_counts.most_common(2)]
                                
                                for rng in top_rngs:
                                    if rng not in bot_settings["voltx_services"][srv][full_country_name]:
                                        bot_settings["voltx_services"][srv][full_country_name].append(rng)
                                        changed = True
                                        
                                    country_code = rng[:3]
                                    if country_code not in bot_settings["voltx_search_countries"]:
                                        bot_settings["voltx_search_countries"].append(country_code)
                                        changed = True

                        services_to_remove = []
                        for srv, countries in list(bot_settings["voltx_services"].items()):
                            srv_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and "real_range" in t and current_time - t.get("time", 0) <= 120)
                            if srv_hit < 1:
                                services_to_remove.append(srv)
                                continue
                            
                            countries_to_remove = []
                            for country, ranges in list(countries.items()):
                                c_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and get_flag_info_html(t.get("iso"), return_full_name=True).title() == country and "real_range" in t and current_time - t.get("time", 0) <= 120)
                                if c_hit < 1:
                                    countries_to_remove.append(country)
                                    continue
                                
                                ranges_to_remove = []
                                for rng in ranges:
                                    r_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and t.get("real_range") == rng and current_time - t.get("time", 0) <= 120)
                                    if r_hit < 1: 
                                        ranges_to_remove.append(rng)
                                
                                for r in ranges_to_remove:
                                    ranges.remove(r)
                                    changed = True
                                    
                            for c in countries_to_remove:
                                del bot_settings["voltx_services"][srv][c]
                                changed = True
                                
                        for s in services_to_remove:
                            del bot_settings["voltx_services"][s]
                            changed = True
                            
                        if changed:
                            save_db()
                            
        except Exception as e:
            pass
        time.sleep(10)

def voltx_sms_listener():
    global processed_otps, recent_traffic, voltx_assigned_numbers
    while True:
        try:
            voltx_keys = bot_settings.get("voltx_keys", [])
            for api_key in voltx_keys:
                try:
                    headers = {"mauthapi": api_key}
                    res = requests.get(f"{VOLTX_BASE_URL}/success-otp", headers=headers, timeout=10)
                    resp_data = res.json()
                    
                    if resp_data.get("meta", {}).get("code") == 200 and "data" in resp_data and "otps" in resp_data["data"]:
                        for item in resp_data["data"]["otps"]:
                            num = str(item.get("number", "")).replace("+", "")
                            msg_text = str(item.get("message", ""))
                            otp = extract_otp_code(msg_text) or "CODE"
                            otp_id = str(item.get("otp_id", otp))
                            
                            app_name = "Voltx Service"
                            detected_app = detect_service(msg_text)
                            if detected_app: app_name = detected_app
                                
                            unique_id = f"VOLTX_{num}_{otp_id}"
                            
                            if unique_id not in processed_otps and num:
                                processed_otps.add(unique_id)
                                if len(processed_otps) > 5000: processed_otps.clear()
                                
                                char, iso = get_flag_and_code(num)
                                app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                                current_time = time.time()
                                
                                recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                                recent_traffic.append({"service": app_full_name, "iso": iso, "flag": char, "number": num, "time": current_time})
                                save_local_db()
                                
                                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                                masked = mask_number(display_num)
                                lang = detect_language(msg_text)
                                
                                lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                display_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {masked} | 💬 {lang_name}")
                                
                                for fw in bot_settings.get("fw_groups", []):
                                    kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                                    temp_row = []
                                    styles = ["danger", "success", "primary"]
                                    for i, btn in enumerate(fw.get("buttons", [])):
                                        b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                                        if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                                        temp_row.append(b_obj)
                                        if len(temp_row) == 2:
                                            kb.append(temp_row)
                                            temp_row = []
                                    if temp_row: kb.append(temp_row)
                                    send_message(fw["chat_id"], display_msg, reply_markup={"inline_keyboard": kb})
                                    
                                owner_id = None
                                clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                
                                for uid, session_data in user_active_sessions.items():
                                    for act_num in session_data.get("nums", []):
                                        act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                            owner_id = uid
                                            break
                                    if owner_id: break
                                    
                                if not owner_id:
                                    for vtx_n, n_owner in voltx_assigned_numbers.items():
                                        clean_vtx = str(vtx_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if clean_vtx == clean_api_num or (len(clean_vtx) >= 8 and clean_vtx.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_vtx[-8:])):
                                            owner_id = n_owner
                                            break
                                        
                                if owner_id:
                                    lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                    inbox_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {display_num} | 💬 {lang_name}")
                                    inbox_kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": otp}, "style": "success"}]]
                                    
                                    reward = float(assigned_number_rates.get(num, bot_settings.get("otp_reward", 0.0)))
                                    if reward > 0:
                                        update_balance(owner_id, reward)
                                        inbox_kb.append([{"text": f"Added {reward} tk", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                    
                                    send_message(owner_id, inbox_msg, reply_markup={"inline_keyboard": inbox_kb})
                                    
                                    record_user_otp(owner_id, otp)
                except: pass
        except: pass
        time.sleep(5)

def zenex_sms_listener():
    global processed_otps, recent_traffic, zenex_assigned_numbers
    while True:
        try:
            zenex_keys = bot_settings.get("zenex_keys", [])
            for api_key in zenex_keys:
                try:
                    headers = {"mapikey": api_key}
                    res = requests.get(f"{ZENEX_BASE_URL}/v1/numsuccess/info", headers=headers, timeout=10)
                    resp_data = res.json()
                    
                    if resp_data.get("meta", {}).get("code") == 200 and "data" in resp_data and "otps" in resp_data["data"]:
                        for item in resp_data["data"]["otps"]:
                            num = str(item.get("number", "")).replace("+", "")
                            msg_text = str(item.get("otp", ""))
                            otp = extract_otp_code(msg_text) or "CODE"
                            otp_id = str(item.get("nid", otp))
                            
                            app_name = "Zenex Service"
                            detected_app = detect_service(msg_text)
                            if detected_app: app_name = detected_app
                                
                            unique_id = f"ZENEX_{num}_{otp_id}"
                            
                            if unique_id not in processed_otps and num:
                                processed_otps.add(unique_id)
                                if len(processed_otps) > 5000: processed_otps.clear()
                                
                                char, iso = get_flag_and_code(num)
                                app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                                current_time = time.time()
                                
                                recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                                recent_traffic.append({"service": app_full_name, "iso": iso, "flag": char, "number": num, "time": current_time})
                                save_local_db()
                                
                                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                                masked = mask_number(display_num)
                                lang = detect_language(msg_text)
                                
                                lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                display_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {masked} | 💬 {lang_name}")
                                
                                for fw in bot_settings.get("fw_groups", []):
                                    kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                                    temp_row = []
                                    styles = ["danger", "success", "primary"]
                                    for i, btn in enumerate(fw.get("buttons", [])):
                                        b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                                        if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                                        temp_row.append(b_obj)
                                        if len(temp_row) == 2:
                                            kb.append(temp_row)
                                            temp_row = []
                                    if temp_row: kb.append(temp_row)
                                    send_message(fw["chat_id"], display_msg, reply_markup={"inline_keyboard": kb})
                                    
                                owner_id = None
                                clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                
                                for uid, session_data in user_active_sessions.items():
                                    for act_num in session_data.get("nums", []):
                                        act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                            owner_id = uid
                                            break
                                    if owner_id: break
                                    
                                if not owner_id:
                                    for znx_n, n_owner in zenex_assigned_numbers.items():
                                        clean_znx = str(znx_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if clean_znx == clean_api_num or (len(clean_znx) >= 8 and clean_znx.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_znx[-8:])):
                                            owner_id = n_owner
                                            break
                                        
                                if owner_id:
                                    inbox_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {display_num} | 💬 {lang_name}")
                                    inbox_kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": otp}, "style": "success"}]]
                                    
                                    reward = float(assigned_number_rates.get(num, bot_settings.get("otp_reward", 0.0)))
                                    if reward > 0:
                                        update_balance(owner_id, reward)
                                        inbox_kb.append([{"text": f"Added {reward} tk", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                    
                                    send_message(owner_id, inbox_msg, reply_markup={"inline_keyboard": inbox_kb})
                                    
                                    record_user_otp(owner_id, otp)
                except: pass
        except: pass
        time.sleep(5)

def global_sms_listener():
    global processed_otps, recent_traffic, stex_assigned_numbers
    while True:
        try:
            stex_keys = bot_settings.get("stex_keys", [])
            for api_key in stex_keys:
                try:
                    headers = {"mauthapi": api_key}
                    res = requests.get(f"{STEX_BASE_URL}/success-otp", headers=headers, timeout=10)
                    resp_data = res.json()
                    
                    if resp_data.get("meta", {}).get("code") == 200 and "data" in resp_data and "otps" in resp_data["data"]:
                        for item in resp_data["data"]["otps"]:
                            num = str(item.get("number", "")).replace("+", "")
                            msg_text = str(item.get("message", ""))
                            otp = extract_otp_code(msg_text) or "CODE"
                            otp_id = str(item.get("otp_id", otp))
                            
                            app_name = "Stex Service"
                            detected_app = detect_service(msg_text)
                            if detected_app: app_name = detected_app
                                
                            unique_id = f"STEX_{num}_{otp_id}"
                            
                            if unique_id not in processed_otps and num:
                                processed_otps.add(unique_id)
                                if len(processed_otps) > 5000: processed_otps.clear()
                                
                                char, iso = get_flag_and_code(num)
                                app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                                current_time = time.time()
                                
                                recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                                recent_traffic.append({"service": app_full_name, "iso": iso, "flag": char, "number": num, "time": current_time})
                                save_local_db()
                                
                                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                                masked = mask_number(display_num)
                                lang = detect_language(msg_text)
                                
                                lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                display_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {masked} | 💬 {lang_name}")
                                
                                for fw in bot_settings.get("fw_groups", []):
                                    kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5296369303661067030", "copy_text": {"text": otp}, "style": "success"}]]
                                    temp_row = []
                                    styles = ["danger", "success", "primary"]
                                    for i, btn in enumerate(fw.get("buttons", [])):
                                        b_obj = {"text": btn["text"], "url": btn["url"], "style": styles[i % 3]}
                                        if "icon_custom_emoji_id" in btn: b_obj["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
                                        temp_row.append(b_obj)
                                        if len(temp_row) == 2:
                                            kb.append(temp_row)
                                            temp_row = []
                                    if temp_row: kb.append(temp_row)
                                    send_message(fw["chat_id"], display_msg, reply_markup={"inline_keyboard": kb})
                                    
                                owner_id = None
                                clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                
                                for uid, session_data in user_active_sessions.items():
                                    for act_num in session_data.get("nums", []):
                                        act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                            owner_id = uid
                                            break
                                    if owner_id: break
                                    
                                if not owner_id:
                                    for stex_n, n_owner in stex_assigned_numbers.items():
                                        clean_stex = str(stex_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if clean_stex == clean_api_num or (len(clean_stex) >= 8 and clean_stex.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_stex[-8:])):
                                            owner_id = n_owner
                                            break
                                        
                                if owner_id:
                                    lang_name = LANG_MAP.get(lang, "English") if 'LANG_MAP' in globals() else lang.replace("#", "")
                                    inbox_msg = render_body_text(f"{get_flag_info_html(display_num)} {iso} | {prem_app_html} {display_num} | 💬 {lang_name}")
                                    inbox_kb = [[{"text": f"{otp}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": otp}, "style": "success"}]]
                                    
                                    reward = float(assigned_number_rates.get(num, bot_settings.get("otp_reward", 0.0)))
                                    if reward > 0:
                                        update_balance(owner_id, reward)
                                        inbox_kb.append([{"text": f"Added {reward} tk", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                    
                                    send_message(owner_id, inbox_msg, reply_markup={"inline_keyboard": inbox_kb})
                                    
                                    record_user_otp(owner_id, otp)
                except: pass
        except: pass
        time.sleep(5)

def zenex_console_listener():
    global recent_traffic, bot_settings
    last_auto_update = time.time()
    zenex_last_hits = {} 
    
    while True:
        try:
            zenex_keys = bot_settings.get("zenex_keys", [])
            if zenex_keys:
                api_key = zenex_keys[0]
                headers = {"mapikey": api_key}
                res = requests.get(f"{ZENEX_BASE_URL}/v1/active-ranges", headers=headers, timeout=10)
                data = res.json()
                
                if data.get("success") and "data" in data and "active_ranges" in data["data"]:
                    current_time = time.time()
                    new_hits_added = False
                    
                    for hit in data["data"]["active_ranges"]:
                        range_str = str(hit.get("range", "")).replace("X", "").replace("x", "")
                        sid = str(hit.get("service", "Unknown")).upper()
                        hits_count = int(hit.get("hits", 1))
                        
                        if range_str:
                            char, iso = get_flag_and_code(range_str)
                            app_full_name, _ = get_service_info_html(sid, "")
                            
                            range_key = f"{range_str}_{app_full_name}"
                            prev_hits = zenex_last_hits.get(range_key, 0)
                            
                            if hits_count > prev_hits:
                                new_hits = hits_count - prev_hits
                            else:
                                new_hits = hits_count
                                
                            zenex_last_hits[range_key] = hits_count
                            if new_hits > 150: new_hits = 150
                            
                            for _ in range(new_hits):
                                recent_traffic.append({
                                    "service": app_full_name,
                                    "iso": iso,
                                    "flag": char,
                                    "number": f"{range_str}XXX", 
                                    "time": current_time,
                                    "real_range": range_str,
                                    "source": "zenex"
                                })
                                new_hits_added = True
                            
                    if new_hits_added:
                        recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= 3600]
                        save_local_db()
                        
                    if bot_settings.get("zenex_auto", False) and current_time - last_auto_update > 120:
                        last_auto_update = current_time
                        changed = False
                        
                        if "zenex_services" not in bot_settings: bot_settings["zenex_services"] = {}
                        if "zenex_search_countries" not in bot_settings: bot_settings["zenex_search_countries"] = []
                        
                        srv_counts = Counter(t["service"].upper() for t in recent_traffic if t.get("source") == "zenex" and "real_range" in t)
                        top_srvs = [s for s, c in srv_counts.most_common(6)]
                        
                        for srv in top_srvs:
                            if srv not in bot_settings["zenex_services"]:
                                bot_settings["zenex_services"][srv] = {}
                                changed = True
                                
                            iso_counts = Counter(t["iso"] for t in recent_traffic if t.get("service", "").upper() == srv and t.get("source") == "zenex" and "real_range" in t)
                            top_isos = [i for i, c in iso_counts.most_common(3)]
                            
                            for iso in top_isos:
                                full_country_name = get_flag_info_html(iso, return_full_name=True).title()
                                if full_country_name not in bot_settings["zenex_services"][srv]:
                                    bot_settings["zenex_services"][srv][full_country_name] = []
                                    changed = True
                                    
                                rng_counts = Counter(t["real_range"] for t in recent_traffic if t.get("service", "").upper() == srv and t.get("iso") == iso and t.get("source") == "zenex" and "real_range" in t)
                                top_rngs = [r for r, c in rng_counts.most_common(2)]
                                
                                for rng in top_rngs:
                                    if rng not in bot_settings["zenex_services"][srv][full_country_name]:
                                        bot_settings["zenex_services"][srv][full_country_name].append(rng)
                                        changed = True
                                        
                                    country_code = rng[:3]
                                    if country_code not in bot_settings["zenex_search_countries"]:
                                        bot_settings["zenex_search_countries"].append(country_code)
                                        changed = True

                        services_to_remove = []
                        for srv, countries in list(bot_settings["zenex_services"].items()):
                            srv_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and t.get("source") == "zenex" and "real_range" in t and current_time - t.get("time", 0) <= 120)
                            if srv_hit < 1:
                                services_to_remove.append(srv)
                                continue
                            
                            countries_to_remove = []
                            for country, ranges in list(countries.items()):
                                c_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and get_flag_info_html(t.get("iso"), return_full_name=True).title() == country and t.get("source") == "zenex" and "real_range" in t and current_time - t.get("time", 0) <= 120)
                                if c_hit < 1:
                                    countries_to_remove.append(country)
                                    continue
                                
                                ranges_to_remove = []
                                for rng in ranges:
                                    r_hit = sum(1 for t in recent_traffic if t.get("service", "").upper() == srv.upper() and t.get("real_range") == rng and t.get("source") == "zenex" and current_time - t.get("time", 0) <= 120)
                                    if r_hit < 1: 
                                        ranges_to_remove.append(rng)
                                
                                for r in ranges_to_remove:
                                    ranges.remove(r)
                                    changed = True
                                    
                            for c in countries_to_remove:
                                del bot_settings["zenex_services"][srv][c]
                                changed = True
                                
                        for s in services_to_remove:
                            del bot_settings["zenex_services"][s]
                            changed = True
                            
                        if changed:
                            save_db()
                            
        except Exception as e:
            pass
        time.sleep(10)


def start_health_server():
    """Keep Render/UptimeRobot health checks green without a web framework."""
    try:
        port = int(os.getenv("PORT", "10000"))
    except ValueError:
        port = 10000

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/health", "/healthz"):
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({
                "ok": True,
                "service": "gx-number-bot",
                "database": "google_sheets_only",
                "persistent_storage": "Google Sheets",
                "bot_namespace": BOT_NAMESPACE,
                "google_sheets": google_sheets_configured(),
                "time": datetime.utcnow().isoformat() + "Z"
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"🌐 Health server listening on port {port}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except Exception as exc:
        print(f"⚠️ Health server could not start: {exc}")


def monthly_reset_thread():
    while True:
        try:
            ensure_monthly_data_reset()
        except Exception as exc:
            print(f"⚠️ Monthly reset check failed: {exc}")
        time.sleep(60)


def main():
    global BOT_USERNAME
    if not TOKEN:
        print("❌ BOT_TOKEN is missing. Add it as a Render environment variable.")
        return
    # Google Sheets is the only persistent source.  Load it before any update
    # handler or sync thread can run, so a restart never starts from an empty
    # in-memory store and overwrites the sheet.
    load_google_sheet_data()
    start_health_server()
    threading.Thread(target=monthly_reset_thread, daemon=True).start()
    threading.Thread(target=google_sheets_sync_thread, daemon=True).start()
    res = api_call("getMe")
    if res.get("ok"): BOT_USERNAME = res["result"]["username"]
    print(f"🤖 Bot is starting... @{BOT_USERNAME}")
    
    threading.Thread(target=panel_monitor_thread, daemon=True).start()
    threading.Thread(target=global_sms_listener, daemon=True).start()
    threading.Thread(target=stex_console_listener, daemon=True).start()
    threading.Thread(target=voltx_sms_listener, daemon=True).start()
    threading.Thread(target=voltx_console_listener, daemon=True).start()
    threading.Thread(target=zenex_sms_listener, daemon=True).start()
    threading.Thread(target=zenex_console_listener, daemon=True).start()
    print("📡 Background APIs & Global SMS Listener Started!")
    
    executor = ThreadPoolExecutor(max_workers=500)
    
    offset = None
    while True:
        try:
            updates = api_call(f"getUpdates?timeout=50&offset={offset}")
            if updates and "result" in updates:
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update: 
                        executor.submit(handle_message, update["message"])
                    elif "callback_query" in update: 
                        executor.submit(handle_callback, update["callback_query"])
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    main()
