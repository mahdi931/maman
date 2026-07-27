import asyncio
import json
import os
import re
import random
from datetime import datetime, timedelta
import aiohttp

from splusthon import SoroushClient, events
from splusthon.sessions import StringSession
from splusthon.errors import RPCError
from splusthon.tl.functions.channels import EditBannedRequest
from splusthon.tl.types import ChatBannedRights

# =============================================
# تنظیمات
# =============================================
SESSION_FILE = "baranam.txt"
DATA_FILE = "group_data.json"
OWNER_ID = 64427168  # ❗️حتماً آیدی عددی خودت را جایگزین کن

BAD_WORDS = ["کیر", "کص", "کس", "کونی", "جنده", "حرومزاده", "خارکصه", "کصکش", "کیرکش", "گوه", "گاگ"]

CATEGORIES = {
    "جوک": "jock", "حدیث": "hadis", "فال": "fal", "فکت": "fact",
    "دعا": "doa", "دانستنی": "dnstni", "دقت": "deghat", "داستان": "dastan",
    "چیستان": "chistan", "بیو": "bio", "انگیزشی": "angizeshi", "خاطره": "khatereh",
    "خطبه": "khotbeh", "پ ن پ": "pnp", "تکست": "text", "چالش": "chalesh"
}

LOCK_NAMES = {
    "لینک": "link", "فوروارد": "forward", "فحش": "badword", "تکراری": "duplicate",
    "هشتگ": "hashtag", "گروه": "group", "ایموجی": "emoji", "گیف": "gif",
    "استیکر": "sticker", "عکس": "photo", "فایل": "file", "مخاطب": "contact",
    "مکان": "location", "اسپویلر": "spoiler", "فیلم": "video",
    "فیلم سلفی": "video_self", "آهنگ": "audio", "ویس": "voice"
}

DICE_FACES = ["●", "●●", "●●●", "●●\n●●", "●●●\n●", "●●●\n●●●"]

HELP_TEXT = """🤖 **راهنمای ربات مدیریت گروه**

⚙️ فعال/غیرفعال کردن ربات (فقط مالک)
/start | /stop

🛡 **مدیریت کاربران** (ادمین و مالک)
• بن آیدی | رفع بن آیدی
• سکوت آیدی | رفع سکوت آیدی
• اخطار آیدی | حذف اخطار آیدی
• سنجاق (ریپلای) | حذف سنجاق
• لینک
• آیدی (یا آیدی 123456)

🧹 **پاک‌سازی**
• پاک تعداد(کمتر از 100)

🔐 **قفل‌ها** (فقط مالک)
برای فعال کردن: قفل لینک | قفل فوروارد | قفل فحش | ...
برای غیرفعال کردن: بازکردن لینک | بازکردن فوروارد | ...

📝 **فیلتر کلمات** (فقط مالک)
• فیلتر کلمه | فیلتر کلمه بن | فیلتر کلمه سکوت
• حذف فیلتر کلمه | لیست فیلتر | پاکسازی فیلتر

🎉 **سرگرمی‌ها**
• فعال کردن جوک | غیرفعال کردن فال | ...
• دستورات عمومی: جوک | حدیث | فال | فکت | دعا | دانستنی | دقت | داستان | چیستان | بیو | انگیزشی | خاطره | خطبه | پ ن پ | تکست | چالش
• چالش (چالش تصادفی) | تاس | ساعت | تاریخ | بگو متن | سلام

🛡 **ضد اسپم** (فقط مالک)
• ضد اسپم روشن | ضد اسپم خاموش

👑 **مدیریت مالک/ادمین** (فقط مالک)
• افزودن مالک آیدی | حذف مالک آیدی
• افزودن ادمین آیدی | حذف ادمین آیدی

📊 **آمار** (مالک)
• آمار (نمایش آمار گروه)
• آمار روشن | آمار خاموش

💡 **نکته:** برای بن/سکوت/اخطار می‌توانید روی پیام کاربر ریپلای بزنید و فقط دستور را بفرستید (بدون آیدی).
مثال: ریپلای روی پیام + «بن»"""

# =============================================
# ابزارهای داده
# =============================================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_group(chat_id, group):
    groups[str(chat_id)] = group
    save_data(groups)

def get_group(chat_id):
    chat_id = str(chat_id)
    if chat_id not in groups:
        groups[chat_id] = {
            "enabled": False,
            "owners": [],
            "admins": [],
            "locks": {v: False for v in LOCK_NAMES.values()},
            "filters": {},
            "warnings": {},
            "mutes": {},
            "bans": [],
            "fun_enabled": {cat: True for cat in CATEGORIES},
            "antispam": {"enabled": False, "time": 5, "max_msg": 5},
            "stats_enabled": False,
            "last_messages": {},
            "spam_data": {},
            "stats": {}
        }
        save_group(chat_id, groups[chat_id])
    return groups[chat_id]

groups = load_data()

def is_owner(chat_id, user_id):
    group = get_group(chat_id)
    return user_id == OWNER_ID or user_id in group["owners"]

def is_admin(chat_id, user_id):
    group = get_group(chat_id)
    return is_owner(chat_id, user_id) or user_id in group["admins"]

# ===== تابع API با aiohttp (کاملاً غیرهمگام) =====
async def get_fun_api_async(category):
    url = "https://l8pStudio.ir/apis-loop/api-fun.php"
    payload = {"category": CATEGORIES.get(category, category)}
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status"):
                        return data['data']['content']
    except asyncio.TimeoutError:
        return "⏰ زمان پاسخ‌دهی API به پایان رسید."
    except Exception:
        pass
    return "❌ خطا در دریافت محتوا."

def extract_user_id(text):
    parts = text.strip().split()
    for part in parts[1:]:
        if part.isdigit():
            return int(part)
    return None

def is_valid_target(chat_id, target_id, sender_id):
    if target_id is None:
        return False, "❌ لطفاً آیدی عددی کاربر را وارد کنید یا روی پیام او ریپلای کنید."
    if not isinstance(target_id, int) or target_id <= 0:
        return False, "❌ شناسه کاربر نامعتبر است."
    if target_id == OWNER_ID:
        return False, "❌ نمی‌توانید به مالک اصلی ربات دستور دهید."
    group = get_group(chat_id)
    if target_id in group["owners"]:
        return False, "❌ نمی‌توانید به مالک‌های گروه دستور دهید."
    if target_id in group["admins"] and not is_owner(chat_id, sender_id):
        return False, "❌ فقط مالک می‌تواند به ادمین‌ها دستور دهد."
    return True, ""

async def get_user_entity(client, user_id):
    try:
        return await client.get_input_entity(user_id)
    except:
        return None

async def ban_user(client, chat_id, user_id):
    user_entity = await get_user_entity(client, user_id)
    if user_entity is None:
        return False, "کاربر در گروه یافت نشد یا ربات به او دسترسی ندارد."

    chat_entity = await client.get_input_entity(chat_id)
    rights = ChatBannedRights(
        until_date=None,
        view_messages=True,
        send_messages=True,
        send_media=True,
        send_stickers=True,
        send_gifs=True,
        send_games=True,
        send_inline=True,
        embed_links=True,
        send_polls=True,
        change_info=True,
        invite_users=True,
        pin_messages=True
    )
    try:
        await client(EditBannedRequest(chat_entity, user_entity, rights))
        return True, ""
    except RPCError as e:
        return False, f"خطای RPC: {e}"
    except Exception as e:
        return False, f"خطای ناشناخته: {e}"

async def unban_user(client, chat_id, user_id):
    user_entity = await get_user_entity(client, user_id)
    if user_entity is None:
        return False, "کاربر در گروه یافت نشد یا ربات به او دسترسی ندارد."

    chat_entity = await client.get_input_entity(chat_id)
    rights = ChatBannedRights(until_date=None, view_messages=False)
    try:
        await client(EditBannedRequest(chat_entity, user_entity, rights))
        return True, ""
    except RPCError as e:
        return False, f"خطای RPC: {e}"
    except Exception as e:
        return False, f"خطای ناشناخته: {e}"

# =============================================
# راه‌اندازی ربات
# =============================================
if os.path.exists(SESSION_FILE):
    with open(SESSION_FILE, "r") as f:
        session_string = f.read().strip()
else:
    session_string = None

client = SoroushClient(StringSession(session_string))

@client.on(events.NewMessage)
async def handle_all(event):
    if event.message.out:
        return

    text = event.text.strip() if event.text else ""
    chat_id = event.chat_id
    sender = await event.get_sender()
    sender_id = sender.id
    is_private = event.is_private

    if is_private:
        return

    group = get_group(chat_id)

    # ===== استخراج دستور و هدف اولیه =====
    parts = text.split()
    cmd = parts[0] if parts else ""
    target = extract_user_id(text)   # ابتدا از متن آیدی می‌گیریم

    # ===== اگر دستور بن/سکوت/اخطار باشد و ریپلای شده باشد و آیدی در متن نباشد، از ریپلای آیدی می‌گیریم =====
    if cmd in ("بن", "سکوت", "اخطار") and event.message.reply_to_msg_id and target is None:
        try:
            reply_msg = await client.get_messages(chat_id, ids=event.message.reply_to_msg_id)
            if reply_msg and reply_msg.sender_id:
                target = reply_msg.sender_id
        except:
            pass

    # فعال/غیرفعال
    if text == "/start":
        if is_owner(chat_id, sender_id):
            group["enabled"] = True
            save_group(chat_id, group)
            await event.reply("✅ ربات در گروه فعال شد.")
        else:
            await event.reply("⛔ فقط مالک ربات می‌تواند ربات را فعال کند.")
        return
    if text == "/stop":
        if is_owner(chat_id, sender_id):
            group["enabled"] = False
            save_group(chat_id, group)
            await event.reply("🛑 ربات غیرفعال شد.")
        else:
            await event.reply("⛔ فقط مالک ربات می‌تواند ربات را متوقف کند.")
        return

    if not group["enabled"]:
        return

    # بن
    if sender_id in group["bans"]:
        await event.delete()
        return

    # سکوت
    mute_until_str = group["mutes"].get(str(sender_id))
    if mute_until_str:
        mute_until = datetime.fromisoformat(mute_until_str)
        if datetime.now() < mute_until:
            await event.delete()
            return
        else:
            del group["mutes"][str(sender_id)]
            save_group(chat_id, group)

    # آمار
    if group["stats_enabled"]:
        uid = str(sender_id)
        group["stats"][uid] = group["stats"].get(uid, 0) + 1

    # ضد اسپم
    if group["antispam"]["enabled"]:
        now = datetime.now()
        spam_data = group["spam_data"]
        user_spam = spam_data.get(str(sender_id))
        if user_spam:
            first_time = datetime.fromisoformat(user_spam["first_time"])
            if (now - first_time).seconds <= group["antispam"]["time"]:
                user_spam["count"] += 1
                if user_spam["count"] > group["antispam"]["max_msg"]:
                    group["mutes"][str(sender_id)] = (now + timedelta(minutes=60)).isoformat()
                    await event.delete()
                    await event.reply(f"🔇 کاربر {sender_id} به دلیل اسپم 60 دقیقه سکوت شد.")
                    del group["spam_data"][str(sender_id)]
                    save_group(chat_id, group)
                    return
            else:
                group["spam_data"][str(sender_id)] = {"count": 1, "first_time": now.isoformat()}
        else:
            group["spam_data"][str(sender_id)] = {"count": 1, "first_time": now.isoformat()}
        save_group(chat_id, group)

    # قفل‌ها
    locks = group["locks"]
    if locks["link"] and text and re.search(r'(https?://\S+|www\.\S+|\S+\.\S{2,})', text):
        await event.delete()
        return
    if locks["forward"] and event.message.forward:
        await event.delete()
        return
    # بهبود فحش‌یابی: چک کردن کلمه کامل
    if locks["badword"] and text:
        words_in_message = text.split()
        if any(bw in words_in_message for bw in BAD_WORDS):
            await event.delete()
            return
    if locks["duplicate"] and text:
        last_entry = group["last_messages"].get(str(sender_id))
        if last_entry:
            last_text, last_time_str = last_entry
            last_time = datetime.fromisoformat(last_time_str)
            if last_text == text and (datetime.now() - last_time).seconds < 10:
                await event.delete()
                return
        group["last_messages"][str(sender_id)] = (text, datetime.now().isoformat())

    # فیلتر کلمات
    for word, punishment in group["filters"].items():
        if word in text:
            if punishment == "ban":
                if sender_id not in group["bans"]:
                    success, _ = await ban_user(client, chat_id, sender_id)
                    if success:
                        group["bans"].append(sender_id)
                await event.delete()
                await event.reply(f"🚫 کاربر {sender_id} به دلیل کلمه «{word}» بن شد.")
            elif punishment == "mute":
                group["mutes"][str(sender_id)] = (datetime.now() + timedelta(hours=1)).isoformat()
                await event.delete()
                await event.reply(f"🔇 کاربر {sender_id} به دلیل کلمه «{word}» سکوت شد.")
            elif punishment == "warn":
                warns = group["warnings"].get(str(sender_id), 0) + 1
                group["warnings"][str(sender_id)] = warns
                await event.delete()
            save_group(chat_id, group)
            return

    # ===== دستورات عمومی =====
    if text == "راهنما":
        await event.reply(HELP_TEXT)
        return
    if text == "چالش":
        await event.reply(await get_fun_api_async("چالش"))
        return
    if text == "تاس":
        await event.reply(f"🎲 تاس:\n{random.choice(DICE_FACES)}")
        return
    if text == "آیدی" or text.startswith("آیدی "):
        uid = extract_user_id(text)
        if uid:
            await event.reply(f"🆔 آیدی کاربر: `{uid}`")
        else:
            await event.reply(f"🆔 آیدی شما: `{sender_id}`")
        return
    if text in CATEGORIES:
        if group["fun_enabled"].get(text, False):
            await event.reply(await get_fun_api_async(text))
        else:
            await event.reply("⛔ این بخش توسط مالک غیرفعال شده است.")
        return
    if text.startswith("ربات"):
        await event.reply("فعالم")
        return
    if text.startswith("بگو"):
        await event.reply(text[4:])
        return
    if text == "ساعت":
        await event.reply(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
        return
    if text == "تاریخ":
        await event.reply(f"📅 {datetime.now().strftime('%Y-%m-%d')}")
        return
    if text == "سلام":
        await event.reply("سلام! 👋")
        return

    # فقط ادمین/مالک از اینجا به بعد
    if not is_admin(chat_id, sender_id):
        # اگر دستور نیاز به مجوز دارد، پیام خطا
        if text and cmd in ("بن", "سکوت", "اخطار", "سنجاق", "حذف", "لینک",
                             "قفل", "بازکردن", "فیلتر", "لیست", "پاکسازی",
                             "فعال", "غیرفعال", "ضد", "افزودن", "آمار"):
            await event.reply("⛔ شما دسترسی لازم برای این دستور را ندارید.")
        return

    # اعتبارسنجی دستورات نیازمند آیدی (target ممکن است از متن یا ریپلای باشد)
    if cmd in ("بن", "سکوت", "اخطار"):
        valid, msg = is_valid_target(chat_id, target, sender_id)
        if not valid:
            await event.reply(msg)
            return

    # --- مدیریت کاربران ---
    if cmd == "بن" and target:
        success, err_msg = await ban_user(client, chat_id, target)
        if success:
            if target not in group["bans"]:
                group["bans"].append(target)
            await event.reply(f"🚫 کاربر {target} بن شد.")
        else:
            if target in group["bans"]:
                group["bans"].remove(target)
            await event.reply(f"❌ بن انجام نشد: {err_msg}")
        save_group(chat_id, group)

    elif cmd == "رفع" and len(parts) > 1 and parts[1] == "بن":
        uid = target if target else (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None)
        if uid:
            success, _ = await unban_user(client, chat_id, uid)
            if success and uid in group["bans"]:
                group["bans"].remove(uid)
            await event.reply("✅ کاربر از بن خارج شد." if success else "❌ رفع بن ناموفق بود.")
        else:
            await event.reply("❌ آیدی نامعتبر است.")
        save_group(chat_id, group)

    elif cmd == "سکوت" and target:
        group["mutes"][str(target)] = (datetime.now() + timedelta(hours=1)).isoformat()
        await event.reply(f"🔇 کاربر {target} یک ساعت سکوت شد.")
        save_group(chat_id, group)

    elif cmd == "رفع" and len(parts) > 1 and parts[1] == "سکوت":
        uid = target if target else (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None)
        if uid and str(uid) in group["mutes"]:
            del group["mutes"][str(uid)]
            await event.reply("🔊 سکوت کاربر برداشته شد.")
        else:
            await event.reply("❌ کاربر سکوت نشده یا آیدی نامعتبر.")
        save_group(chat_id, group)

    elif cmd == "حذف" and len(parts) > 1 and parts[1] == "اخطار":
        uid = target if target else (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None)
        if uid and str(uid) in group["warnings"]:
            group["warnings"][str(uid)] = max(0, group["warnings"][str(uid)] - 1)
            await event.reply(f"♻️ یک اخطار کم شد (کاربر {uid}).")
        else:
            await event.reply("❌ کاربر اخطار ندارد یا آیدی نامعتبر.")
        save_group(chat_id, group)

    elif cmd == "سنجاق":
        if event.message.reply_to_msg_id:
            try:
                await client.pin_message(chat_id, event.message.reply_to_msg_id)
                await event.reply("📌 پیام سنجاق شد.")
            except Exception as e:
                await event.reply(f"❌ خطا در سنجاق: {e}")
        else:
            await event.reply("❌ لطفاً روی پیام مورد نظر ریپلای کنید.")

    elif cmd == "حذف" and len(parts) > 1 and parts[1] == "سنجاق":
        try:
            await client.unpin_message(chat_id)
            await event.reply("🗑 سنجاق حذف شد.")
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")

    # --- پاکسازی پیام‌ها ---
    elif cmd == "پاک" and len(parts) > 1:
        if parts[1] == "همه":
            # فقط OWNER_ID مجاز به پاک کردن همه پیام‌هاست
            if sender_id != OWNER_ID:
                await event.reply("⛔ فقط مالک اصلی ربات می‌تواند همه پیام‌ها را پاک کند.")
                return
            try:
                while True:
                    msgs = await client.get_messages(chat_id, limit=100)
                    if not msgs:
                        break
                    await client.delete_messages(chat_id, [m.id for m in msgs])
                await event.reply("✅ تمام پیام‌ها پاک شدند.")
            except RPCError as e:
                await event.reply(f"❌ خطا: {e}")
        elif parts[1].isdigit():
            count = int(parts[1])
            if 0 < count <= 100:
                # برای پاک کردن تعداد مشخص، ادمین‌ها و مالک‌ها مجازند
                if not is_admin(chat_id, sender_id):
                    await event.reply("⛔ شما دسترسی لازم برای این دستور را ندارید.")
                    return
                try:
                    messages = await client.get_messages(chat_id, limit=count)
                    msg_ids = [m.id for m in messages]
                    await client.delete_messages(chat_id, msg_ids)
                    await event.reply(f"✅ {len(msg_ids)} پیام پاک شد.")
                except RPCError as e:
                    await event.reply(f"❌ خطا: {e}")
        else:
            await event.reply("❌ دستور پاک نامعتبر. مثال: پاک 10 یا پاک همه")

    # --- قفل و بازکردن (فقط مالک) ---
    elif cmd in ("قفل", "بازکردن"):
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ این دستور مخصوص مالک ربات است.")
            return
        if len(parts) < 2:
            await event.reply("❌ لطفاً نام قفل را بنویسید. مثال: قفل لینک")
            return
        lock_persian = " ".join(parts[1:])
        lock_key = LOCK_NAMES.get(lock_persian)
        if lock_key is None:
            await event.reply(f"❌ نام قفل «{lock_persian}» معتبر نیست.")
            return
        if cmd == "قفل":
            group["locks"][lock_key] = True
            await event.reply(f"🔒 قفل {lock_persian} فعال شد.")
        else:  # بازکردن
            group["locks"][lock_key] = False
            await event.reply(f"🔓 قفل {lock_persian} باز شد.")
        save_group(chat_id, group)

    # ========== فیلتر کلمات (فقط مالک) ==========
    elif cmd == "فیلتر":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند فیلتر اضافه کند.")
            return
        if len(parts) < 2:
            await event.reply("❌ لطفاً کلمه را مشخص کنید. مثال: فیلتر تبلیغ")
            return
        word = parts[1]
        punishment = "warn"
        if len(parts) > 2 and parts[2] in ("بن", "سکوت", "اخطار"):
            punishment = {"بن": "ban", "سکوت": "mute", "اخطار": "warn"}[parts[2]]
        group["filters"][word] = punishment
        await event.reply(f"✅ کلمه «{word}» با مجازات {punishment} فیلتر شد.")
        save_group(chat_id, group)

    elif cmd == "حذف" and len(parts) > 1 and parts[1] == "فیلتر":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند فیلترها را حذف کند.")
            return
        if len(parts) < 3:
            await event.reply("❌ لطفاً کلمه را بنویسید. مثال: حذف فیلتر تبلیغ")
            return
        word = parts[2]
        if word not in group["filters"]:
            await event.reply(f"❌ کلمه «{word}» در لیست فیلترها وجود ندارد.")
        else:
            del group["filters"][word]
            await event.reply(f"🗑 فیلتر «{word}» حذف شد.")
            save_group(chat_id, group)

    elif cmd == "لیست" and len(parts) > 1 and parts[1] == "فیلتر":
        if not is_admin(chat_id, sender_id):  # حتی ادمین هم می‌تونه لیست رو ببینه
            await event.reply("⛔ دسترسی ندارید.")
            return
        if group["filters"]:
            txt = "\n".join([f"{w}: {p}" for w, p in group["filters"].items()])
            await event.reply(f"📝 لیست فیلترها:\n{txt}")
        else:
            await event.reply("📝 لیست فیلتر خالی است.")

    elif cmd in ("پاکسازی", "پاک‌سازی") and len(parts) > 1 and parts[1] == "فیلتر":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند فیلترها را پاکسازی کند.")
            return
        group["filters"] = {}
        await event.reply("🧹 تمام فیلترها پاک شدند.")
        save_group(chat_id, group)

    # --- کنترل سرگرمی ---
    elif cmd in ("فعال", "غیرفعال") and len(parts) > 2 and parts[1] == "کردن":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند بخش‌های سرگرمی را مدیریت کند.")
            return
        fun = " ".join(parts[2:])
        if fun in CATEGORIES:
            if cmd == "فعال":
                group["fun_enabled"][fun] = True
                await event.reply(f"✅ {fun} فعال شد.")
            else:
                group["fun_enabled"][fun] = False
                await event.reply(f"⛔ {fun} غیرفعال شد.")
            save_group(chat_id, group)
        else:
            await event.reply(f"❌ بخش «{fun}» پیدا نشد.")

    # --- ضد اسپم ---
    elif cmd == "ضد" and len(parts) > 2 and parts[1] == "اسپم":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند ضد اسپم را مدیریت کند.")
            return
        if parts[2] == "روشن":
            group["antispam"]["enabled"] = True
            await event.reply("🛡 ضد اسپم فعال شد.")
        elif parts[2] == "خاموش":
            group["antispam"]["enabled"] = False
            await event.reply("🛡 ضد اسپم غیرفعال شد.")
        else:
            await event.reply("❌ استفاده: ضد اسپم روشن | ضد اسپم خاموش")
        save_group(chat_id, group)

    # --- آمار ---
    elif cmd == "آمار":
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک می‌تواند آمار را ببیند.")
            return
        if len(parts) == 1:
            stats = group["stats"]
            if stats:
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
                txt = "\n".join([f"کاربر {uid}: {cnt}" for uid, cnt in sorted_stats])
                await event.reply(f"📊 ۱۰ کاربر برتر:\n{txt}")
            else:
                await event.reply("هنوز آماری ثبت نشده.")
        elif len(parts) > 1:
            if parts[1] == "روشن":
                group["stats_enabled"] = True
                await event.reply("📊 آمار خودکار روشن شد.")
            elif parts[1] == "خاموش":
                group["stats_enabled"] = False
                await event.reply("📊 آمار خودکار خاموش شد.")
            elif parts[1] == "گروه":
                stats = group["stats"]
                if stats:
                    sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
                    txt = "\n".join([f"کاربر {uid}: {cnt}" for uid, cnt in sorted_stats])
                    await event.reply(f"📊 ۱۰ کاربر برتر:\n{txt}")
                else:
                    await event.reply("هنوز آماری ثبت نشده.")
            else:
                await event.reply("❌ استفاده: آمار | آمار روشن | آمار خاموش | آمار گروه")
        save_group(chat_id, group)

    # --- مدیریت مالک/ادمین (با پشتیبانی از ریپلای) ---
    elif cmd in ("افزودن", "حذف") and len(parts) > 1:
        if not is_owner(chat_id, sender_id):
            await event.reply("⛔ فقط مالک اصلی می‌تواند مالک/ادمین اضافه کند.")
            return
        
        # اگر target نداریم و ریپلای شده، از ریپلای بگیر
        if target is None and event.message.reply_to_msg_id:
            try:
                reply_msg = await client.get_messages(chat_id, ids=event.message.reply_to_msg_id)
                if reply_msg and reply_msg.sender_id:
                    target = reply_msg.sender_id
            except:
                pass
        
        # اگر باز هم target نداریم، خطا بده
        if target is None:
            await event.reply("❌ لطفاً آیدی کاربر را وارد کنید یا روی پیام او ریپلای کنید.")
            return
        
        role = parts[1]
        if role not in ("مالک", "ادمین"):
            await event.reply("❌ استفاده: افزودن مالک 123456 / افزودن ادمین 123456")
            return
        
        # جلوگیری از تغییر نقش OWNER_ID
        if target == OWNER_ID:
            await event.reply("❌ نمی‌توانید مالک اصلی ربات را تغییر دهید.")
            return
        
        if cmd == "افزودن":
            if role == "مالک":
                if target not in group["owners"]:
                    group["owners"].append(target)
                    await event.reply(f"👑 کاربر {target} به مالک اضافه شد.")
                else:
                    await event.reply("❌ کاربر قبلاً مالک است.")
            else:  # ادمین
                if target not in group["admins"]:
                    group["admins"].append(target)
                    await event.reply(f"🛡 کاربر {target} به ادمین اضافه شد.")
                else:
                    await event.reply("❌ کاربر قبلاً ادمین است.")
        else:  # حذف
            if role == "مالک":
                if target in group["owners"]:
                    group["owners"].remove(target)
                    await event.reply(f"❌ کاربر {target} از مالکیت حذف شد.")
                else:
                    await event.reply("❌ کاربر در لیست مالکان نیست.")
            else:  # ادمین
                if target in group["admins"]:
                    group["admins"].remove(target)
                    await event.reply(f"❌ ادمین {target} حذف شد.")
                else:
                    await event.reply("❌ کاربر در لیست ادمین‌ها نیست.")
        save_group(chat_id, group)

    # اگر دستوری بود که شناخته نشد ولی به نظر ادمین/مالک است
    else:
        return

# =============================================
# اجرا با مدیریت اتصال مجدد
# =============================================
async def main():
    while True:
        try:
            await client.start()
            session_string = client.session.save()
            with open(SESSION_FILE, "w") as f:
                f.write(session_string)
            print("✨ ربات با موفقیت راه‌اندازی شد...")
            await client.run_until_disconnected()
        except (ConnectionError, Exception) as e:
            print(f"⚠️ اتصال قطع شد: {e}. تلاش مجدد در ۵ ثانیه...")
            await asyncio.sleep(5)
            continue
        break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("⏹️ ربات متوقف شد.")