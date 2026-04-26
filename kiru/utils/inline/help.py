from typing import Union
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from kiru import app
from config import OWNER_ID 

def help_pannel(_, START: Union[bool, int] = None):
    # 1 se 15 tak buttons ka data
    buttons_data = [
        ("H_B_1", "hb1"), ("H_B_2", "hb2"), ("H_B_3", "hb3"),
        ("H_B_4", "hb4"), ("H_B_5", "hb5"), ("H_B_6", "hb6"),
        ("H_B_7", "hb7"), ("H_B_8", "hb8"), ("H_B_9", "hb9"),
        ("H_B_10", "hb10"), ("H_B_11", "hb11"), ("H_B_12", "hb12"),
        ("H_B_13", "hb13"), ("H_B_14", "hb14"), ("H_B_15", "hb15")
    ]

    # 3x5 Grid logic
    rows = []
    for i in range(0, len(buttons_data), 3):
        row = [
            InlineKeyboardButton(text=_[btn_text], callback_data=f"help_callback {cb}")
            for btn_text, cb in buttons_data[i:i+3]
        ]
        rows.append(row)

    # Back aur Close button logic
    if START:
        footer = [InlineKeyboardButton(text=_["BACK_BUTTON"], callback_data="settingsback_helper")]
    else:
        footer = [InlineKeyboardButton(text=_["CLOSE_BUTTON"], callback_data="close")]
    
    rows.append(footer)
    
    # Owner Button
    rows.append([InlineKeyboardButton(text="ᴏᴡɴᴇʀ", url=f"tg://user?id={OWNER_ID}")])

    return InlineKeyboardMarkup(rows)

def help_back_markup(_):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=_["BACK_BUTTON"], callback_data="settingsback_helper")]]
    )

def private_help_panel(_):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=_["S_B_4"], url=f"https://t.me/{app.username}?start=help")]]
            )
