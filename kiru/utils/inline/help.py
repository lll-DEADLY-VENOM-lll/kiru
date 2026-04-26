from pyrogram import types
import config 

class HelpPanel:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def help_markup(self, _lang: dict, back: bool = False) -> types.InlineKeyboardMarkup:
        # Language keys missing hone par default text set kiya gaya hai
        back_text = _lang.get("back", "ʙᴀᴄᴋ")
        close_text = _lang.get("close", "ᴄʟᴏsᴇ")
        
        if back:
            # Jab koi specific help menu ke andar ho tab 'Back' button dikhane ke liye
            rows = [[self.ikb(text=back_text, callback_data="settings_back_helper"), 
                     self.ikb(text=close_text, callback_data="close")]]
        else:
            # Main Help Menu: Yahan saari categories dikhengi
            cbs = ["admins", "auth", "blist", "lang", "ping", "play", "queue", "stats", "sudo"]
            buttons = []
            for cb in cbs:
                text = _lang.get(f"help_{cb}", cb.capitalize())
                buttons.append(self.ikb(text=text, callback_data=f"help_callback hb{cbs.index(cb) + 1}"))
            
            # Buttons ko 3 columns mein divide karne ke liye
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
            # Owner button niche add karein
            rows.append([self.ikb(text="ᴏᴡɴᴇʀ", url=f"tg://user?id={config.OWNER_ID}")])
            
        return self.ikm(rows)

    def help_back_markup(self, _lang: dict) -> types.InlineKeyboardMarkup:
        back_text = _lang.get("back", "ʙᴀᴄᴋ")
        close_text = _lang.get("close", "ᴄʟᴏsᴇ")
        rows = [[
            self.ikb(text=back_text, callback_data="settings_back_helper"), 
            self.ikb(text=close_text, callback_data="close")
        ]]
        return self.ikm(rows)

# --- Sahi Exports taaki plugin crash na ho ---
_hp = HelpPanel()

# Yeh 'help_pannel' ab ek function ki tarah kaam karega (Fixes: TypeError: object is not callable)
help_pannel = _hp.help_markup
help_back_markup = _hp.help_back_markup

def private_help_panel(_):
    # Groups mein jab /help likhte hain tab yeh button dikhta hai
    buttons = [
        [
            types.InlineKeyboardButton(
                text="Hᴇʟᴘ",
                url=f"https://t.me/{config.BOT_USERNAME}?start=help",
            ),
        ],
    ]
    return buttons
