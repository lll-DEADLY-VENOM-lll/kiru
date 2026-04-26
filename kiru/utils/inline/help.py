from pyrogram import types
import config 

class HelpPanel:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def help_markup(self, _lang: dict, back: bool = False) -> types.InlineKeyboardMarkup:
        # .get() use karne se KeyError nahi aayega
        back_text = _lang.get("back", "ʙᴀᴄᴋ")
        close_text = _lang.get("close", "ᴄʟᴏsᴇ")
        
        if back:
            rows = [[self.ikb(text=back_text, callback_data="help back"), 
                     self.ikb(text=close_text, callback_data="help close")]]
        else:
            cbs = ["admins", "auth", "blist", "lang", "ping", "play", "queue", "stats", "sudo"]
            buttons = []
            for cb in cbs:
                # Agar language file mein key na mile toh default text
                text = _lang.get(f"help_{cb}", cb.capitalize())
                buttons.append(self.ikb(text=text, callback_data=f"help {cb}"))
            
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
            rows.append([self.ikb(text="ᴏᴡɴᴇʀ", url=f"tg://user?id={config.OWNER_ID}")])
            
        return self.ikm(rows)

    def help_back_markup(self, _lang: dict) -> types.InlineKeyboardMarkup:
        back_text = _lang.get("back", "ʙᴀᴄᴋ")
        close_text = _lang.get("close", "ᴄʟᴏsᴇ")
        rows = [[
            self.ikb(text=back_text, callback_data="help back"), 
            self.ikb(text=close_text, callback_data="help close")
        ]]
        return self.ikm(rows)

# Exports
_hp = HelpPanel()
help_pannel = _hp.help_markup
help_back_markup = _hp.help_back_markup

def private_help_panel(_):
    # Safe text for Help button
    text = _.get("help_1", "Hᴇʟᴘ") if isinstance(_, dict) else "Hᴇʟᴘ"
    buttons = [
        [
            types.InlineKeyboardButton(
                text="Hᴇʟᴘ",
                callback_data="settings_back_helper",
            ),
        ],
    ]
    return buttons
