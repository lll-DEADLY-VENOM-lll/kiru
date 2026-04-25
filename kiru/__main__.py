import asyncio
import importlib
from pyrogram import idle
from pytgcalls.exceptions import NoActiveGroupCall

import config
from kiru import LOGGER, app, userbot
from kiru.core.call import Anony
from kiru.misc import sudo
from kiru.plugins import ALL_MODULES
from kiru.utils.database import get_banned_users, get_gbanned
from config import BANNED_USERS

async def init():
    # 1. Assistant Clients Check
    if not any([config.STRING1, config.STRING2, config.STRING3, config.STRING4, config.STRING5]):
        LOGGER(__name__).error("Assistant client variables (STRING1-5) defined nahi hain.")
        return

    await sudo()

    # 2. Database se Banned Users load karna
    try:
        users = await get_gbanned()
        for user_id in users:
            BANNED_USERS.add(user_id)
        users = await get_banned_users()
        for user_id in users:
            BANNED_USERS.add(user_id)
    except Exception as e:
        LOGGER(__name__).warning(f"Banned users loading error: {e}")

    # 3. Clients Start
    await app.start()
    await userbot.start()
    await Anony.start()
    LOGGER("kiru").info("Sare Clients Start ho gaye hain.")

    # 4. Plugins Import (Fixing Plugging Error)
    for all_module in ALL_MODULES:
        try:
            # "kiru.plugins." ensure karta hai ki path sahi ho
            module_path = "kiru.plugins." + all_module if not all_module.startswith(".") else "kiru.plugins" + all_module
            importlib.import_module(module_path)
        except Exception as e:
            LOGGER("kiru.plugins").error(f"Module {all_module} load nahi ho paya: {e}")

    LOGGER("kiru.plugins").info("Plugins Import Process Complete.")

    # 5. Call Setup
    try:
        await Anony.stream_call("https://te.legra.ph/file/29f784eb49d230ab62e9e.mp4")
    except NoActiveGroupCall:
        LOGGER("kiru").error("Video Chat on karein! Bot band ho raha hai...")
        return
    except Exception as e:
        LOGGER("kiru").warning(f"Stream call error: {e}")

    await Anony.decorators()
    LOGGER("kiru").info("Kiru Music Bot is now Online!")

    # 6. Idle - Bot ko chalu rakhne ke liye
    await idle()

    # 7. Graceful Shutdown (RuntimeWarning fix yahan hai)
    LOGGER("kiru").info("Shutting down... Pending tasks clean kiye ja rahe hain.")
    
    # Clients ko stop karne se pehle thoda wait taaki tasks finish ho sakein
    if app.is_connected:
        await app.stop()
    if userbot.is_connected:
        await userbot.stop()
    
    LOGGER("kiru").info("Bot Successfully Stopped.")

if __name__ == "__main__":
    # Event loop handling for Python 3.10+
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init())
    except KeyboardInterrupt:
        # User ne Ctrl+C dabaya
        pass
    except Exception as e:
        LOGGER("kiru").error(f"Fatal Error: {e}")
    finally:
        # Loop band karne se pehle ensure karein ki sab clean ho
        if loop.is_running():
            loop.close()
