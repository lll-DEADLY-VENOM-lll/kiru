from typing import Union
from pyrogram import filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from kiru import app
from kiru.utils.database import get_lang
from kiru.utils.decorators.language import LanguageStart, languageCB
from config import BANNED_USERS, START_IMG_URL, SUPPORT_CHAT
from strings import get_string, helpers

# --- Buttons Layout (Clean 2-Column) ---
def get_help_keyboard(_):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="Admin", callback_data="help_callback hb1"),
                InlineKeyboardButton(text="Auth", callback_data="help_callback hb2"),
            ],
            [
                InlineKeyboardButton(text="Broadcast", callback_data="help_callback hb3"),
                InlineKeyboardButton(text="Bl-Chat", callback_data="help_callback hb4"),
            ],
            [
                InlineKeyboardButton(text="Bl-User", callback_data="help_callback hb5"),
                InlineKeyboardButton(text="C-Play", callback_data="help_callback hb6"),
            ],
            [
                InlineKeyboardButton(text="G-Ban", callback_data="help_callback hb7"),
                InlineKeyboardButton(text="Loop", callback_data="help_callback hb8"),
            ],
            [
                InlineKeyboardButton(text="Maintenance", callback_data="help_callback hb9"),
                InlineKeyboardButton(text="Ping", callback_data="help_callback hb10"),
            ],
            [
                InlineKeyboardButton(text="Play", callback_data="help_callback hb11"),
                InlineKeyboardButton(text="Shuffle", callback_data="help_callback hb12"),
            ],
            [
                InlineKeyboardButton(text="Seek", callback_data="help_callback hb13"),
                InlineKeyboardButton(text="Song", callback_data="help_callback hb14"),
            ],
            [
                InlineKeyboardButton(text="Speed", callback_data="help_callback hb15"),
            ],
            [
                InlineKeyboardButton(text="Back", callback_data="settings_back_helper"),
            ],
        ]
    )

def help_back_markup(_):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="Back", callback_data="settings_back_helper")]]
    )

# --- Handlers ---

@app.on_message(filters.command(["help"]) & filters.private & ~BANNED_USERS)
@app.on_callback_query(filters.regex("settings_back_helper") & ~BANNED_USERS)
async def helper_private(
    client: app, update: Union[types.Message, types.CallbackQuery]
):
    is_callback = isinstance(update, types.CallbackQuery)
    chat_id = update.message.chat.id if is_callback else update.chat.id
    
    if is_callback:
        try:
            await update.answer()
        except:
            pass
    else:
        try:
            await update.delete()
        except:
            pass
            
    language = await get_lang(chat_id)
    _ = get_string(language)
    keyboard = get_help_keyboard(_)
    caption = _["help_1"].format(SUPPORT_CHAT)

    if is_callback:
        await update.edit_message_text(caption, reply_markup=keyboard)
    else:
        await update.reply_photo(
            photo=START_IMG_URL,
            caption=caption,
            reply_markup=keyboard,
        )

@app.on_message(filters.command(["help"]) & filters.group & ~BANNED_USERS)
@LanguageStart
async def help_com_group(client, message: Message, _):
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="Help Menu", url=f"t.me/{app.username}?start=help")]]
    )
    await message.reply_text(_["help_2"], reply_markup=keyboard)

@app.on_callback_query(filters.regex("help_callback") & ~BANNED_USERS)
@languageCB
async def helper_cb(client, CallbackQuery, _):
    callback_data = CallbackQuery.data.strip()
    cb = callback_data.split(None, 1)[1]
    keyboard = help_back_markup(_)
    
    help_text = {
        "hb1": helpers.HELP_1, "hb2": helpers.HELP_2, "hb3": helpers.HELP_3,
        "hb4": helpers.HELP_4, "hb5": helpers.HELP_5, "hb6": helpers.HELP_6,
        "hb7": helpers.HELP_7, "hb8": helpers.HELP_8, "hb9": helpers.HELP_9,
        "hb10": helpers.HELP_10, "hb11": helpers.HELP_11, "hb12": helpers.HELP_12,
        "hb13": helpers.HELP_13, "hb14": helpers.HELP_14, "hb15": helpers.HELP_15,
    }

    if cb in help_text:
        await CallbackQuery.edit_message_text(help_text[cb], reply_markup=keyboard)
