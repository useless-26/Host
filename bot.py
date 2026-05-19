import os
import sys
import asyncio
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

# ============ CONFIG ============
TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', 0))

if not TOKEN or not OWNER_ID:
    print("❌ Error: BOT_TOKEN and OWNER_ID required!")
    sys.exit(1)

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
SCRIPTS_DIR = BASE_DIR / "scripts"
SCRIPTS_DIR.mkdir(exist_ok=True)

# Bot initialization
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Store running scripts
running_scripts = {}

# ============ KEYBOARDS ============
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Upload Script", callback_data="upload")],
        [InlineKeyboardButton(text="📁 My Scripts", callback_data="list")],
        [InlineKeyboardButton(text="🔄 Running Scripts", callback_data="running")],
        [InlineKeyboardButton(text="ℹ️ Help", callback_data="help")]
    ])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu")]
    ])

# ============ HANDLERS ============
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Unauthorized! Only owner can use this bot.")
        return
    
    await message.answer(
        "🚀 **Python Script Hosting Bot**\n\n"
        "Upload and run Python scripts easily!\n"
        "Use buttons below to get started.",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🏠 **Main Menu**\n\nChoose an option:",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "upload")
async def upload_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📤 **Upload Python Script**\n\n"
        "Send me a `.py` file.\n"
        "File will be saved and ready to run.",
        reply_markup=back_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "list")
async def list_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_scripts_dir = SCRIPTS_DIR / str(user_id)
    
    if not user_scripts_dir.exists():
        await callback.message.edit_text(
            "📁 **No scripts found**\n\nUpload a script first!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    scripts = list(user_scripts_dir.glob("*.py"))
    
    if not scripts:
        await callback.message.edit_text(
            "📁 **No scripts found**\n\nUpload a script first!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = f"📁 **Your Scripts ({len(scripts)})**\n\n"
    buttons = []
    
    for script in scripts:
        script_name = script.name
        text += f"📄 `{script_name}`\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"▶️ {script_name[:20]}",
                callback_data=f"run:{script_name}"
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=f"delete:{script_name}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "running")
async def running_callback(callback: types.CallbackQuery):
    if not running_scripts:
        await callback.message.edit_text(
            "🔄 **No scripts running**\n\nAll scripts are stopped.",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = f"🔄 **Running Scripts ({len(running_scripts)})**\n\n"
    buttons = []
    
    for script_id, info in running_scripts.items():
        text += f"📄 `{info['name']}` (PID: {info['pid']})\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"🛑 Stop {info['name'][:20]}",
                callback_data=f"stop:{script_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_callback(callback: types.CallbackQuery):
    help_text = """
ℹ️ **Help Guide**

**Commands:**
/start - Start the bot

**Features:**
📤 Upload - Send .py files
▶️ Run - Execute Python scripts
🛑 Stop - Stop running scripts
🗑️ Delete - Remove scripts

**Limits:**
- Max 50 scripts per user
- Max 10 concurrent scripts
- Script timeout: 1 hour

**Support:** @YourUsername
"""
    await callback.message.edit_text(
        help_text,
        reply_markup=back_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(F.document)
async def handle_upload(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Unauthorized!")
        return
    
    document = message.document
    file_name = document.file_name
    
    if not file_name.endswith('.py'):
        await message.answer("❌ Only `.py` files are allowed!")
        return
    
    user_id = message.from_user.id
    user_scripts_dir = SCRIPTS_DIR / str(user_id)
    user_scripts_dir.mkdir(exist_ok=True)
    
    # Check limit (max 50 scripts)
    existing_scripts = list(user_scripts_dir.glob("*.py"))
    if len(existing_scripts) >= 50:
        await message.answer("❌ Max 50 scripts allowed! Delete some first.")
        return
    
    file_path = user_scripts_dir / file_name
    
    try:
        await message.answer(f"📤 Uploading `{file_name}`...", parse_mode="Markdown")
        
        await bot.download(document, destination=file_path)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Run Script", callback_data=f"run:{file_name}")],
            [InlineKeyboardButton(text="📁 My Scripts", callback_data="list")]
        ])
        
        await message.answer(
            f"✅ **Script uploaded!**\n\n📄 `{file_name}`\n💾 Size: {document.file_size} bytes",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await message.answer(f"❌ Upload failed: {str(e)}")

@dp.callback_query(F.data.startswith("run:"))
async def run_script(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    script_name = callback.data.split(":")[1]
    
    script_path = SCRIPTS_DIR / str(user_id) / script_name
    
    if not script_path.exists():
        await callback.answer("❌ Script not found!", show_alert=True)
        return
    
    # Check running limit (max 10 concurrent)
    user_scripts_running = sum(1 for s in running_scripts.values() if s['owner'] == user_id)
    if user_scripts_running >= 10:
        await callback.answer("❌ Max 10 scripts running at once!", show_alert=True)
        return
    
    script_id = f"{user_id}_{script_name}_{datetime.now().timestamp()}"
    
    try:
        # Create log file
        log_path = SCRIPTS_DIR / str(user_id) / f"{script_name}.log"
        log_file = open(log_path, 'w')
        
        # Run script
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=log_file,
            stderr=log_file,
            cwd=str(SCRIPTS_DIR / str(user_id))
        )
        
        running_scripts[script_id] = {
            'name': script_name,
            'pid': process.pid,
            'process': process,
            'owner': user_id,
            'log_file': log_file,
            'start_time': datetime.now()
        }
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Stop Script", callback_data=f"stop:{script_id}")],
            [InlineKeyboardButton(text="📄 View Logs", callback_data=f"logs:{script_id}")],
            [InlineKeyboardButton(text="📁 My Scripts", callback_data="list")]
        ])
        
        await callback.message.edit_text(
            f"✅ **Script running!**\n\n📄 `{script_name}`\n🆔 PID: `{process.pid}`\n\nUse buttons to manage.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer(f"✅ {script_name} started!")
        
    except Exception as e:
        await callback.answer(f"❌ Error: {str(e)}", show_alert=True)

@dp.callback_query(F.data.startswith("stop:"))
async def stop_script(callback: types.CallbackQuery):
    script_id = callback.data.split(":")[1]
    
    if script_id not in running_scripts:
        await callback.answer("❌ Script not running!", show_alert=True)
        return
    
    try:
        script_info = running_scripts[script_id]
        process = script_info['process']
        
        # Close log file
        if 'log_file' in script_info and script_info['log_file']:
            script_info['log_file'].close()
        
        # Kill process
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        
        del running_scripts[script_id]
        
        await callback.answer(f"✅ Script stopped!", show_alert=True)
        await list_callback(callback)
        
    except Exception as e:
        await callback.answer(f"❌ Error: {str(e)}", show_alert=True)

@dp.callback_query(F.data.startswith("logs:"))
async def view_logs(callback: types.CallbackQuery):
    script_id = callback.data.split(":")[1]
    
    if script_id not in running_scripts:
        await callback.answer("❌ Script not running!", show_alert=True)
        return
    
    script_info = running_scripts[script_id]
    user_id = callback.from_user.id
    log_path = SCRIPTS_DIR / str(user_id) / f"{script_info['name']}.log"
    
    if not log_path.exists():
        await callback.answer("No logs yet!", show_alert=True)
        return
    
    try:
        with open(log_path, 'r') as f:
            logs = f.read()[-2000:]  # Last 2000 characters
        
        if not logs:
            logs = "No output yet..."
        
        # Split if too long
        if len(logs) > 3500:
            logs = logs[:3500] + "\n\n... (truncated)"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Stop Script", callback_data=f"stop:{script_id}")],
            [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"logs:{script_id}")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="running")]
        ])
        
        await callback.message.edit_text(
            f"📄 **Logs for `{script_info['name']}`**\n\n```\n{logs}\n```",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"Error: {str(e)}", show_alert=True)

@dp.callback_query(F.data.startswith("delete:"))
async def delete_script(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    script_name = callback.data.split(":")[1]
    
    script_path = SCRIPTS_DIR / str(user_id) / script_name
    
    if not script_path.exists():
        await callback.answer("❌ Script not found!", show_alert=True)
        return
    
    # Check if script is running
    for script_id, info in running_scripts.items():
        if info['name'] == script_name and info['owner'] == user_id:
            await callback.answer("❌ Stop script before deleting!", show_alert=True)
            return
    
    try:
        script_path.unlink()
        
        # Delete log file if exists
        log_path = SCRIPTS_DIR / str(user_id) / f"{script_name}.log"
        if log_path.exists():
            log_path.unlink()
        
        await callback.answer(f"✅ {script_name} deleted!", show_alert=True)
        await list_callback(callback)
        
    except Exception as e:
        await callback.answer(f"❌ Error: {str(e)}", show_alert=True)

# ============ WEB SERVER FOR RENDER ============
async def web_server():
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="Bot is running!")
    
    async def stats(request):
        return web.json_response({
            "status": "online",
            "scripts_total": len(running_scripts),
            "scripts_dir": str(SCRIPTS_DIR)
        })
    
    app.router.add_get('/', health_check)
    app.router.add_get('/stats', stats)
    
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"✅ Web server on port {port}")

# ============ MAIN ============
async def main():
    print("🚀 Starting Python Script Hosting Bot...")
    
    # Start web server for Render
    asyncio.create_task(web_server())
    
    # Start bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())