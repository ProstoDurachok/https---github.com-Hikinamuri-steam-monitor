from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

FACETS = {
    "type": {
        "CSGO_Type_Pistol": "Пистолет",
        "CSGO_Type_SMG": "Пистолет-пулемёт",
        "CSGO_Type_Rifle": "Винтовка",
        "CSGO_Type_Shotgun": "Дробовик",
        "CSGO_Type_SniperRifle": "Снайперская винтовка",
        "CSGO_Type_Machinegun": "Пулемёт",
        "CSGO_Type_Knife": "Нож",
    },
    "subcategory": {
        "CSGO_Type_Pistol": {
            "weapon_glock": "Glock-18",
            "weapon_usp_silencer": "USP-S",
            "weapon_hkp2000": "P2000",
            "weapon_p250": "P250",
            "weapon_tec9": "Tec-9",
            "weapon_cz75a": "CZ75-Auto",
            "weapon_deagle": "Desert Eagle",
            "weapon_fiveseven": "Five-SeveN",
            "weapon_elite": "Dual Berettas",
            "weapon_revolver": "Револьвер R8"
        },
        "CSGO_Type_SMG": {
            "weapon_mp9": "MP9",
            "weapon_mac10": "MAC-10",
            "weapon_ump45": "UMP-45",
            "weapon_bizon": "ПП-19 «Бизон»",
            "weapon_mp7": "MP7",
            "weapon_p90": "P90",
            "weapon_mp5sd": "MP5-SD"
        },
        "CSGO_Type_Rifle": {
            "weapon_galilar": "Автомат «Галиль»",
            "weapon_famas": "FAMAS",
            "weapon_ak47": "AK-47",
            "weapon_m4a1": "M4A4",
            "weapon_m4a1_silencer": "M4A1-S",
            "weapon_sg556": "SG 553",
            "weapon_aug": "AUG"
        },
        "CSGO_Type_Shotgun": {
            "weapon_nova": "Nova",
            "weapon_xm1014": "XM1014",
            "weapon_sawedoff": "Sawed-Off",
            "weapon_mag7": "MAG-7"
        },
        "CSGO_Type_SniperRifle": {
            "weapon_ssg08": "SSG 08",
            "weapon_scar20": "SCAR-20",
            "weapon_awp": "AWP",
            "weapon_g3sg1": "G3SG1"
        },
        "CSGO_Type_Machinegun": {
            "weapon_m249": "M249",
            "weapon_negev": "Негев"
        },
        "CSGO_Type_Knife": {
            "weapon_bayonet": "Штык-нож",
            "weapon_knife_flip": "Складной нож",
            "weapon_knife_gut": "Нож с лезвием-крюком",
            "weapon_knife_karambit": "Керамбит",
            "weapon_knife_m9_bayonet": "Штык-нож M9",
            "weapon_knife_tactical": "Охотничий нож",
            "weapon_knife_falchion": "Фальшион",
            "weapon_knife_survival_bowie": "Нож Боуи",
            "weapon_knife_butterfly": "Нож-бабочка",
            "weapon_knife_push": "Тычковые ножи",
            "weapon_knife_ursus": "Медвежий нож",
            "weapon_knife_gypsy_jackknife": "Наваха",
            "weapon_knife_stiletto": "Стилет",
            "weapon_knife_widowmaker": "Коготь",
            "weapon_knife_css": "Классический нож",
            "weapon_knife_cord": "Паракорд-нож",
            "weapon_knife_canis": "Нож выживания",
            "weapon_knife_outdoor": "Нож «Бродяга»",
            "weapon_knife_skeleton": "Скелетный нож",
            "weapon_knife_kukri": "Кукри"
        }
    },
    "exterior": {
        "WearCategory0": "Прямо с завода",
        "WearCategory1": "Немного поношенное",
        "WearCategory2": "После полевых испытаний",
        "WearCategory3": "Поношенное",
        "WearCategory4": "Закалённое в боях",
        "WearCategoryNA": "Не покрашено"
    },
    "itemset": {
        "set_anubis": "Коллекция Anubis",
        "set_assault": "Коллекция Assault",
        "set_aztec": "Коллекция Aztec",
        "set_baggage": "Коллекция Baggage",
        "set_bank": "Коллекция Bank",
        "set_blacksite": "Коллекция Blacksite",
        "set_bravo_i": "Коллекция «Браво»",
        "set_bravo_ii": "Коллекция «Альфа»",
        "set_cache": "Коллекция Cache",
        "set_canals": "Коллекция Canals",
        "set_chopshop": "Коллекция «Чик-чик»",
        "set_cobblestone": "Коллекция Cobblestone",
        "set_community_1": "Коллекция Winter Offensive",
        "set_community_2": "Коллекция «Феникс»",
        "set_community_3": "Охотничья коллекция",
        "set_community_4": "Коллекция «Прорыв»",
        "set_community_5": "Коллекция «Авангард»",
        "set_community_6": "Коллекция из хромированного кейса",
        "set_community_7": "Коллекция из хромированного кейса #2",
        "set_community_8": "Коллекция «Фальшион»",
        "set_community_9": "Коллекция из тёмного кейса",
        "set_community_10": "Револьверная коллекция",
        "set_community_11": "Коллекция «Дикое пламя»",
        "set_community_12": "Коллекция из хромированного кейса #3",
        "set_community_13": "Коллекция «Гамма»",
        "set_community_15": "Перчаточная коллекция",
        "set_community_16": "Коллекция «Спектр»",
        "set_community_17": "Коллекция операции «Гидра»",
        "set_community_18": "Коллекция «Спектр 2»",
        "set_community_19": "Коллекция «Решающий момент»",
        "set_community_20": "Коллекция «Горизонт»",
        "set_community_21": "Коллекция «Запретная зона»",
        "set_community_22": "Коллекция «Призма»",
        "set_community_23": "Коллекция «Расколотая сеть»",
        "set_community_24": "Коллекция CS20",
        "set_community_25": "Коллекция «Призма 2»",
        "set_community_26": "Коллекция «Разлом»",
        "set_community_27": "Коллекция операции «Сломанный клык»",
        "set_community_28": "Коллекция «Змеиный укус»",
        "set_community_29": "Коллекция операции «Хищные воды»",
        "set_community_30": "Коллекция «Грёзы и кошмары»",
        "set_community_31": "Гремучая коллекция",
        "set_community_32": "Коллекция «Революция»",
        "set_community_33": "Коллекция «Киловатт»",
        "set_community_34": "Галерейная коллекция",
        "set_community_35": "Коллекция «Лихорадка»",
        "set_dust": "Коллекция Dust",
        "set_dust_2": "Коллекция Dust 2",
        "set_dust_2_2021": "Коллекция Dust 2 2021",
        "set_esports": "Коллекция eSports 2013",
        "set_esports_ii": "Коллекция eSports Winter 2013",
        "set_esports_iii": "Коллекция eSports 2014 Summer",
        "set_gamma_2": "Коллекция «Гамма 2»",
        "set_gods_and_monsters": "Коллекция «Боги и чудовища»",
        "set_graphic_design": "Коллекция «Графический дизайн»",
        "set_inferno": "Коллекция Inferno",
        "set_inferno_2": "Коллекция Inferno 2018",
        "set_italy": "Коллекция Italy",
        "set_kimono": "Коллекция «Рассвет»",
        "set_lake": "Коллекция Lake",
        "set_militia": "Коллекция Militia",
        "set_mirage": "Коллекция Mirage",
        "set_mirage_2021": "Коллекция Mirage 2021",
        "set_norse": "Коллекция «Север»",
        "set_nuke": "Коллекция Nuke",
        "set_nuke_2": "Коллекция Nuke 2018",
        "set_office": "Коллекция Office",
        "set_op9_characters": "Агенты «Расколотой сети»",
        "set_op10_ancient": "Коллекция Ancient",
        "set_op10_characters": "Агенты «Сломанного клыка»",
        "set_op10_ct": "Коллекция «Контроль»",
        "set_op10_t": "Коллекция «Хаос»",
        "set_op11_characters": "Агенты операции «Хищные воды»",
        "set_overpass": "Коллекция Overpass",
        "set_overpass_2024": "Коллекция Overpass 2024",
        "set_realism_camo": "Коллекция «Спорт и досуг»",
        "set_safehouse": "Коллекция Safehouse",
        "set_stmarc": "Коллекция St. Marc",
        "set_timed_drops_cool": "Коллекция «Восхождение»",
        "set_timed_drops_neutral": "Бореальная коллекция",
        "set_timed_drops_warm": "Коллекция «Расцвет»",
        "set_train": "Коллекция Train",
        "set_train_2021": "Коллекция Train 2021",
        "set_train_2025": "Коллекция Train 2025",
        "set_vertigo": "Коллекция Vertigo",
        "set_vertigo_2021": "Коллекция Vertigo 2021",
        "set_weapons_i": "Коллекция Arms Deal",
        "set_weapons_ii": "Коллекция Arms Deal 2",
        "set_weapons_iii": "Коллекция Arms Deal 3",
        "set_xpshop_wpn_01": "Лимитированный предмет",
        "set_xraymachine": "Коллекция «Рентген»"
    },
    "rarity": {
        "Rarity_Common_Weapon": "Ширпотреб",
        "Rarity_Uncommon_Weapon": "Промышленное качество",
        "Rarity_Rare_Weapon": "Армейское качество",
        "Rarity_Mythical_Weapon": "Запрещённое",
        "Rarity_Legendary_Weapon": "Засекреченное",
        "Rarity_Ancient_Weapon": "Тайное",
        "Rarity_Contraband": "Контрабанда",
        "Rarity_Rare": "Высшего класса",
        "Rarity_Mythical": "Примечательного типа",
        "Rarity_Legendary": "Экзотичного вида",
        "Rarity_Ancient": "Экстраординарного типа",
        "Rarity_Common": "Базового класса",
        "Rarity_Rare_Character": "Заслуженный",
        "Rarity_Mythical_Character": "Исключительный",
        "Rarity_Legendary_Character": "Превосходный",
        "Rarity_Ancient_Character": "Мастерский"
    },
    "quality": {
        "normal": "Обычный",
        "strange": "StatTrak™",
        "tournament": "Сувенирный",
        "unusual": "★",
        "unusual_strange": "★ StatTrak™",
        "highlight": "Яркий момент"
    },
}

def build_filter_keyboard(options_dict, prefix, current_page=0, page_size=9, add_run_button=False):
    keys = list(options_dict.keys())
    total_pages = (len(keys) + page_size - 1) // page_size
    start = current_page * page_size
    end = start + page_size
    page_keys = keys[start:end]
    
    kb = InlineKeyboardBuilder()
    for key in page_keys:
        label = options_dict[key]
        kb.button(text=label, callback_data=f"{prefix}_{key}")
    
    # Pagination buttons
    if total_pages > 1:
        nav_row = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"{prefix}_page_{current_page-1}"))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"{prefix}_page_{current_page+1}"))
        if nav_row:
            kb.row(*nav_row)
    
    kb.button(text="⏭️ Пропустить", callback_data=f"{prefix}_skip")
    if add_run_button:
        kb.button(text="🚀 Запустить скан", callback_data="scan_run")
    kb.adjust(3)
    return kb.as_markup()