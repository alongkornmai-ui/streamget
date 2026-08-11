import os
import json
import asyncio
import logging
import sys
import time
import shutil
import re
import math
import subprocess
import signal
from urllib.parse import urlparse
from datetime import datetime
from PIL import Image

# ─── Telegram Libraries ───
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from streamget import (
    TikTokLiveStream,
    DouyinLiveStream,
    BigoLiveStream,
    TwitchLiveStream,
    YoutubeLiveStream,
    KwaiLiveStream,
    BilibiliLiveStream
)

# ─── 📝 CONFIGURATION ───
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

TOKEN = '8583340382:AAGQxoXa5OsKpOQnp3z7JiqbMQGekrvT2O8'
# URL ของ GitHub Pages ที่รัน Mini App
WEBAPP_URL = "https://alongkornmai-ui.github.io/streamget/"
MY_COOKIE = "sessionid=32a62dc94c0c2ca4bce73bbf9b59fcc8;"

TT_WATCHLIST_FILE = "watchlist.json"
STATUS_JSON_FILE = "status.json"
OUTPUT_DIR = "/storage/emulated/0/Tiktok_videos"
SCAN_INTERVAL = 45

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# Colors for Termux HUD
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Global Variables
active_records_info = {}   
last_check_time = {}       
active_processes = {}      
next_scan_timestamp = 0    
upload_queue = asyncio.Queue()
pending_uploads = {} 
main_chat_id = None
telegram_app = None

# ─── 🔄 GITHUB AUTO-SYNC FUNCTION ───
def sync_status_to_github():
    """สร้าง status.json และ Git Push ขึ้น GitHub Pages อัตโนมัติ"""
    try:
        watchlist_raw = load_json_list(TT_WATCHLIST_FILE)
        
        formatted_watchlist = []
        for item in watchlist_raw:
            _, _, platform = get_stream_client_and_url(item)
            short_name = extract_display_name(item, platform)
            formatted_watchlist.append(short_name)

        active_list = []
        for key, info in list(active_records_info.items()):
            _, _, platform = get_stream_client_and_url(key)
            short_name = extract_display_name(key, platform)
            active_list.append({
                "username": short_name,
                "platform": info.get("platform", "Live"),
                "start_timestamp": info.get("start_timestamp", time.time())
            })

        total_files = len(os.listdir(OUTPUT_DIR)) if os.path.exists(OUTPUT_DIR) else 0

        status_data = {
            "active_list": active_list,
            "watchlist": formatted_watchlist,
            "total_recordings": total_files
        }

        with open(STATUS_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)

        subprocess.run(["git", "add", STATUS_JSON_FILE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", "Auto update status.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push", "origin", "main"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ─── 🔍 HELPER FUNCTIONS ───
def load_json_list(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: 
                return json.load(f)
        except Exception: return []
    return []

def save_json_list(filename, data):
    with open(filename, "w", encoding="utf-8") as f: 
        json.dump(data, f, indent=4, ensure_ascii=False)
    sync_status_to_github()

def format_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"

def get_video_duration(file_path):
    cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{file_path}"'
    try:
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        return float(output)
    except Exception:
        return 0.0

def generate_sample_grid(video_path, output_grid_path, num_samples=12):
    try:
        duration = get_video_duration(video_path)
        if duration <= 0: return False

        temp_dir = os.path.join(OUTPUT_DIR, "temp_snaps")
        os.makedirs(temp_dir, exist_ok=True)

        interval = duration / (num_samples + 1)
        images = []

        for i in range(1, num_samples + 1):
            timestamp = interval * i
            snap_path = os.path.join(temp_dir, f"snap_{i}.jpg")
            cmd = f'ffmpeg -ss {timestamp} -i "{video_path}" -vframes 1 -q:v 2 "{snap_path}" -y'
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(snap_path):
                img = Image.open(snap_path)
                img.thumbnail((300, 300))
                images.append(img)

        if not images: return False

        cols = 3
        rows = math.ceil(len(images) / cols)
        w, h = images[0].size
        grid_img = Image.new('RGB', (cols * w, rows * h), color=(0, 0, 0))

        for idx, img in enumerate(images):
            r = idx // cols
            c = idx % cols
            grid_img.paste(img, (c * w, r * h))

        grid_img.save(output_grid_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return True
    except Exception:
        return False

def extract_display_name(input_str: str, platform: str) -> str:
    text = str(input_str).strip()
    if platform == "BigoLive":
        match = re.search(r'(?:user/|bigo:|^)(\d+)', text, re.IGNORECASE)
        if match: return match.group(1)
        return text.split('/')[-1].split('?')[0]
    elif platform == "TikTok":
        clean_user = text.replace("https://www.tiktok.com/@", "").strip().lstrip('@')
        return clean_user.split('/')[0].split('?')[0]
    else:
        parsed = urlparse(text)
        path = parsed.path.strip('/')
        if path: return path.split('/')[-1].split('?')[0]
        return text

def get_stream_client_and_url(input_str: str):
    text = str(input_str).strip()
    
    # 📌 เพิ่มรองรับ Tango.me
    if "tango.me" in text:
        return "YTDLP", text, "Tango"
    elif "bigo.tv" in text or "bigo.sg" in text or text.lower().startswith("bigo:"):
        clean_id = text.lower().replace("bigo:", "").strip()
        target_url = clean_id if clean_id.startswith("http") else f"https://www.bigo.tv/{clean_id}"
        return BigoLiveStream(), target_url, "BigoLive"
    elif "douyin.com" in text:
        return DouyinLiveStream(cookies=MY_COOKIE), text, "Douyin"
    elif "twitch.tv" in text:
        return TwitchLiveStream(), text, "Twitch"
    elif "youtube.com" in text or "youtu.be" in text:
        return YoutubeLiveStream(), text, "YouTube"
    elif "kuaishou.com" in text or "kwai.com" in text:
        return KwaiLiveStream(), text, "Kuaishou"
    elif "bilibili.com" in text:
        return BilibiliLiveStream(), text, "Bilibili"
    else:
        clean_user = text.replace("https://www.tiktok.com/@", "").strip().lstrip('@')
        target_url = f"https://www.tiktok.com/@{clean_user}/live"
        return TikTokLiveStream(cookies=MY_COOKIE), target_url, "TikTok"

# ─── 🖥️ TERMUX TERMINAL HUD LOOP ───
async def termux_hud_loop():
    while True:
        try:
            watchlist = load_json_list(TT_WATCHLIST_FILE)
            all_items = list(dict.fromkeys(watchlist + list(active_records_info.keys())))
            
            remaining_sec = max(0, int(next_scan_timestamp - time.time())) if next_scan_timestamp > 0 else 0
            now_str = datetime.now().strftime("%H:%M:%S")

            print("\033[H\033[J", end="") # Clear screen

            print(f"{CYAN}{BOLD}=================================================={RESET}")
            print(f"{CYAN}{BOLD}       🎬 LIVE STREAM RECORDER - TERMUX HUD       {RESET}")
            print(f"{CYAN}{BOLD}=================================================={RESET}")
            print(f" 🕒 {now_str} | ⏳ Next Scan: {YELLOW}{BOLD}{remaining_sec}s{RESET} | 📁 Watchlist: {len(watchlist)} | 📤 Queue: {upload_queue.qsize()}")
            print(f"{CYAN}--------------------------------------------------{RESET}")

            if not all_items:
                print(f" {YELLOW}⚠️ Watchlist is empty. Add targets via Telegram!{RESET}")
            else:
                for idx, item in enumerate(all_items, 1):
                    _, _, platform = get_stream_client_and_url(item)
                    short_name = extract_display_name(item, platform)
                    
                    if item in active_records_info:
                        info = active_records_info[item]
                        duration = format_duration(time.time() - info['start_timestamp'])
                        print(f" {idx:2d}. {RED}{BOLD}[REC]  🔴 {short_name}{RESET} ({info['platform']}) | ⏱️ {GREEN}{BOLD}{duration}{RESET}")
                    else:
                        chk_time = last_check_time.get(item, "Wait...")
                        print(f" {idx:2d}. {GREEN}[WAIT] 💤 {short_name}{RESET} ({platform}) | 🕒 {chk_time}")

            print(f"{CYAN}--------------------------------------------------{RESET}")
            print(f" 📊 Active Recording: {RED}{BOLD}{len(active_records_info)}{RESET} | Waiting: {GREEN}{len(all_items) - len(active_records_info)}{RESET}")
            print(f"{CYAN}=================================================={RESET}")

        except Exception:
            pass

        await asyncio.sleep(1)

# ─── 📦 UPLOAD WORKER ───
async def upload_worker():
    while True:
        application, chat_id, file_path = await upload_queue.get()
        try:
            await rcmltb_leech_engine(application, chat_id, file_path)
        except Exception: pass
        finally: upload_queue.task_done()

# ─── 🚀 LEECH ENGINE ───
async def rcmltb_leech_engine(application: Application, chat_id: int, file_path: str):
    if not os.path.exists(file_path): return
    bot = application.bot
    filename = os.path.basename(file_path)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🚀 **[Telegram-Upload Engine]**\nกำลังส่งไฟล์เข้าสู่แชทบอต...\n📄 วิดีโอ: `{filename}`\n📦 ขนาด: {file_size_mb:.2f} MB",
        parse_mode='Markdown'
    )

    cmd = f"telegram-upload --to '@TK_live_engin_bot' \"{file_path}\""
    try:
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if process.returncode == 0:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=f"✅ **ส่งไฟล์สำเร็จเรียบร้อย!**\n📄 วิดีโอ: `{filename}`", parse_mode='Markdown')
            if os.path.exists(file_path): os.remove(file_path)
            sync_status_to_github()
        else:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text="❌ **ล้มเหลวในการส่งไฟล์**")
    except Exception as e:
        await bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=f"❌ **เกิดข้อผิดพลาด:** {e}")

# ─── 🎬 MONITOR & RECORD TASK ───
async def monitor_tt_task(application: Application, chat_id: int, input_item: str):
    key = input_item
    if key in active_records_info: return

    stream_client, target_url, platform_name = get_stream_client_and_url(input_item)
    short_name = extract_display_name(input_item, platform_name)
    last_check_time[key] = datetime.now().strftime("%H:%M:%S")

    try:
        stream_url = None
        
        # 📌 ปรับรองรับการใช้ yt-dlp ดึง URL ไลฟ์สำหรับ Tango
        if stream_client == "YTDLP":
            cmd_get = f'yt-dlp -g "{target_url}"'
            proc = await asyncio.create_subprocess_shell(cmd_get, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                stream_url = stdout.decode().strip().split('\n')[0]
        else:
            web_data = await stream_client.fetch_web_stream_data(target_url)
            stream_obj = await stream_client.fetch_stream_url(web_data)
            stream_url = stream_obj.m3u8_url or stream_obj.flv_url

        if stream_url:
            now_time = time.time()
            start_time_str = datetime.now().strftime("%H:%M:%S")
            active_records_info[key] = {
                "platform": platform_name,
                "start_timestamp": now_time,
                "start_str": start_time_str
            }
            sync_status_to_github()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_name = re.sub(r'[^\w\-]', '_', short_name)
            output_file = os.path.join(OUTPUT_DIR, f"{platform_name}_{clean_name}_{timestamp}.mp4")

            if chat_id:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔴 **พบการถ่ายทอดสด! [{platform_name}]**\n👤 รายการ: `{short_name}`\n⏰ เริ่มบันทึก: `{start_time_str}`",
                    parse_mode='Markdown'
                )

            cmd = f'ffmpeg -i "{stream_url}" -c copy -y "{output_file}"'
            process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            active_processes[key] = process
            await process.communicate()

            if chat_id and os.path.exists(output_file):
                file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                duration_sec = get_video_duration(output_file)
                duration_str = format_duration(duration_sec)
                
                grid_path = os.path.join(OUTPUT_DIR, f"grid_{clean_name}_{timestamp}.jpg")
                has_grid = generate_sample_grid(output_file, grid_path)

                file_id = f"file_{int(time.time())}"
                pending_uploads[file_id] = output_file

                keyboard = [
                    [
                        InlineKeyboardButton("🚀 ยืนยันอัปโหลดขึ้น Telegram", callback_data=f"up_confirm_{file_id}"),
                        InlineKeyboardButton("💾 เก็บไว้ในเครื่อง", callback_data=f"up_skip_{file_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                caption_text = (
                    f"🎬 **{short_name} - Live Recording**\n\n"
                    f"⏱️ **ความยาว:** {duration_str}  ·  💾 **ขนาด:** {file_size_mb:.1f} MB\n"
                    f"🌐 **Platform:** {platform_name}"
                )

                if has_grid and os.path.exists(grid_path):
                    with open(grid_path, 'rb') as photo:
                        await application.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=caption_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                    os.remove(grid_path)
                else:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=caption_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )

    except Exception:
        pass
    finally:
        active_records_info.pop(key, None)
        active_processes.pop(key, None)
        sync_status_to_github()

async def start_background_monitoring(application: Application, chat_id: int):
    global next_scan_timestamp
    while True:
        try:
            next_scan_timestamp = time.time() + SCAN_INTERVAL
            for item in load_json_list(TT_WATCHLIST_FILE):
                if item not in active_records_info:
                    asyncio.create_task(monitor_tt_task(application, chat_id, item))
                    await asyncio.sleep(3)
        except Exception: pass
        await asyncio.sleep(SCAN_INTERVAL)

# ─── 📱 TELEGRAM WEBAPP HANDLER ───
async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        raw_data = update.effective_message.web_app_data.data
        data = json.loads(raw_data)
        
        action = data.get("action")
        value = data.get("value")
        chat_id = update.effective_chat.id

        if action == "RECORD":
            wl = load_json_list(TT_WATCHLIST_FILE)
            if value not in wl:
                wl.append(value)
                save_json_list(TT_WATCHLIST_FILE, wl)

            await update.message.reply_text(f"🚀 **สั่งเริ่มอัดทันที:** `{value}`", parse_mode='Markdown')
            asyncio.create_task(monitor_tt_task(context.application, chat_id, value))

        elif action == "ADD_WATCHLIST":
            wl = load_json_list(TT_WATCHLIST_FILE)
            if value not in wl:
                wl.append(value)
                save_json_list(TT_WATCHLIST_FILE, wl)
                await update.message.reply_text(f"✅ **เพิ่มเข้า Watchlist เรียบร้อย:** `{value}`", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"⚠️ `{value}` มีอยู่ใน Watchlist แล้ว", parse_mode='Markdown')

        elif action == "REMOVE_WATCHLIST":
            wl = load_json_list(TT_WATCHLIST_FILE)
            updated_wl = [x for x in wl if value.lower() not in x.lower()]
            save_json_list(TT_WATCHLIST_FILE, updated_wl)
            await update.message.reply_text(f"❌ **ลบเรียบร้อย:** `{value}`", parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาดจาก WebApp: {e}")

# ─── ⌨️ TELEGRAM HANDLERS ───
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [InlineKeyboardButton("📱 เปิด Mini App", web_app=WebAppInfo(url=WEBAPP_URL))],
        ['📋 Watchlist'],
        ['📦 ไฟล์ค้างอัปโหลด']
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global main_chat_id
    main_chat_id = update.effective_chat.id
    await update.message.reply_text("🎬 **Multi-Platform Recorder Active!**\nดูสถานะเรียลไทม์ได้ที่หน้าจอ Termux หรือกดเปิด Mini App ได้เลยครับ!", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    
    sync_status_to_github()

    if not context.bot_data.get('monitor_running'):
        context.bot_data['monitor_running'] = True
        asyncio.create_task(start_background_monitoring(context.application, update.effective_chat.id))
        asyncio.create_task(upload_worker())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global main_chat_id
    main_chat_id = update.effective_chat.id
    raw_text = update.message.text.strip()
    action = context.user_data.get('action')

    if raw_text == '📋 Watchlist':
        wl = load_json_list(TT_WATCHLIST_FILE)
        kb = []
        
        for idx, item in enumerate(wl):
            _, _, platform = get_stream_client_and_url(item)
            short_name = extract_display_name(item, platform)
            kb.append([InlineKeyboardButton(f"❌ {short_name} ({platform})", callback_data=f"remove_idx_{idx}")])
            
        kb.append([InlineKeyboardButton("➕ Add Channel / URL", callback_data="add_tt_creator")])
        
        await update.message.reply_text("📋 **Watchlist Management:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    if action == 'waiting_for_add_tt':
        wl = load_json_list(TT_WATCHLIST_FILE)
        if raw_text not in wl:
            wl.append(raw_text)
            save_json_list(TT_WATCHLIST_FILE, wl)
            await update.message.reply_text(f"✅ เพิ่มเรียบร้อยแล้ว!", parse_mode='Markdown')
        context.user_data['action'] = None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try: await query.answer()
    except: pass

    if query.data == 'add_tt_creator':
        context.user_data['action'] = 'waiting_for_add_tt'
        await query.message.reply_text("✍️ ส่ง Username (TikTok) หรือ URL เต็ม หรือ `bigo:ID_NUMBER`:")
        
    elif query.data.startswith("remove_idx_"):
        try:
            idx = int(query.data.replace("remove_idx_", ""))
            wl = load_json_list(TT_WATCHLIST_FILE)
            if 0 <= idx < len(wl):
                removed_item = wl.pop(idx)
                save_json_list(TT_WATCHLIST_FILE, wl)
                await query.message.reply_text(f"❌ ลบ `{removed_item}` ออกจาก Watchlist แล้ว", parse_mode='Markdown')
        except Exception as e:
            await query.message.reply_text(f"❌ เกิดข้อผิดพลาดในการลบ: {e}")

    elif query.data.startswith("up_confirm_"):
        file_id = query.data.replace("up_confirm_", "")
        file_path = pending_uploads.get(file_id)
        if file_path and os.path.exists(file_path):
            await upload_queue.put((context.application, query.message.chat_id, file_path))
            await query.message.reply_text(f"⏳ **นำไฟล์เข้าสู่คิวอัปโหลดเรียบร้อยแล้ว!**\n📄 `{os.path.basename(file_path)}`", parse_mode='Markdown')
        else:
            await query.message.reply_text("❌ ไม่พบไฟล์ หรือไฟล์ถูกลบไปแล้ว")

    elif query.data.startswith("up_skip_"):
        file_id = query.data.replace("up_skip_", "")
        file_path = pending_uploads.get(file_id)
        if file_path:
            pending_uploads.pop(file_id, None)
            await query.message.reply_text(f"💾 **บันทึกไว้ในเครื่องเรียบร้อย** (ไม่อัปโหลด)\n📄 `{os.path.basename(file_path)}`", parse_mode='Markdown')

# ─── 🏁 MAIN ENTRY POINT ───
async def post_init(application: Application):
    global telegram_app
    telegram_app = application
    asyncio.create_task(termux_hud_loop())

def main():
    custom_request = HTTPXRequest(connect_timeout=120.0, read_timeout=120.0, write_timeout=120.0)
    
    application = (
        Application.builder()
        .token(TOKEN)
        .request(custom_request)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
