from pyrogram import types
import config # Ya 'from kiru import config' agar aapka setup waisa hai

class HelpPanel:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def help_markup(self, _lang: dict, back: bool = False) -> types.InlineKeyboardMarkup:
        if back:
            rows = [[self.ikb(text=_lang["back"], callback_data="help back"), 
                     self.ikb(text=_lang["close"], callback_data="help close")]]
        else:
            cbs = ["admins", "auth", "blist", "lang", "ping", "play", "queue", "stats", "sudo"]
            buttons = [self.ikb(text=_lang[f"help_{cb}"], callback_data=f"help {cb}") for cb in cbs]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
            # Owner button
            rows.append([self.ikb(text="ᴏᴡɴᴇʀ", url=f"tg://user?id={config.OWNER_ID}")])
            
        return self.ikm(rows)

    # Naya function jo plugin mang raha hai
    def help_back_markup(self, _lang: dict) -> types.InlineKeyboardMarkup:
        rows = [[
            self.ikb(text=_lang["back"], callback_data="help back"), 
            self.ikb(text=_lang["close"], callback_data="help close")
        ]]
        return self.ikm(rows)

# Instance create karein
help_pannel = HelpPanel()

# Yeh lines zaroori hain taaki direct import kaam karein
help_markup = help_pannel.help_markup
help_back_markup = help_pannel.help_back_markup
