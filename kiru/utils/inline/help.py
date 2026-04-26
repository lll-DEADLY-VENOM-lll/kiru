from typing import Union
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from kiru import app
from config import OWNER_ID # Maan lijiye OWNER_ID aapke config file mein hai

class HelpPanel:
    def __init__(self):
        self.ikm = InlineKeyboardMarkup
        self.ikb = InlineKeyboardButton

    def help_markup(self, _, START: Union[bool, int] = None):
        """
        15 Buttons ka 3x5 Grid layout generate karta hai.
        """
        # 1 se 15 tak buttons ki list (Language dictionary keys ke saath)
        buttons_data = [
            ("H_B_1", "hb1"), ("H_B_2", "hb2"), ("H_B_3", "hb3"),
            ("H_B_4", "hb4"), ("H_B_5", "hb5"), ("H_B_6", "hb6"),
            ("H_B_7", "hb7"), ("H_B_8", "hb8"), ("H_B_9", "hb9"),
            ("H_B_10", "hb10"), ("H_B_11", "hb11"), ("H_B_12", "hb12"),
            ("H_B_13", "hb13"), ("H_B_14", "hb14"), ("H_B_15", "hb15")
        ]

        # Buttons ko generate karke 3-3 ke pairs mein split karna
        rows = []
        for i in range(0, len(buttons_data), 3):
            row = [
                self.ikb(text=_[btn_text], callback_data=f"help_callback {cb}")
                for btn_text, cb in buttons_data[i:i+3]
            ]
            rows.append(row)

        # Back aur Close button logic
        if START:
            footer = [self.ikb(text=_["BACK_BUTTON"], callback_data="settingsback_helper")]
        else:
            footer = [self.ikb(text=_["CLOSE_BUTTON"], callback_data="close")]
        
        rows.append(footer)
        
        # Owner button (Optional: Agar aapko 15 buttons ke niche chahiye)
        rows.append([self.ikb(text="ᴏᴡɴᴇʀ", url=f"tg://user?id={OWNER_ID}")])

        return self.ikm(rows)

    def help_back_markup(self, _):
        """
        Sub-menu se wapas help menu mein jaane ke liye button.
        """
        return self.ikm(
            [
                [
                    self.ikb(text=_["BACK_BUTTON"], callback_data="settingsback_helper")
                ]
            ]
        )

    def private_help_panel(self, _):
        """
        Group mein help command use karne par DM ka link dene ke liye.
        """
        return self.ikm(
            [
                [
                    self.ikb(
                        text=_["S_B_4"],
                        url=f"https://t.me/{app.username}?start=help",
                    )
                ]
            ]
        )

# Instance create karein taaki doosre files mein use ho sake
help_panel = HelpPanel()
