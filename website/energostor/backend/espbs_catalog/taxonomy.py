"""Rubrication of the saved server catalog.

The saved payloads carry a ``source_url`` but almost never a category: the
audit found 505 distinct source paths and an empty ``category`` field on every
record.  This module maps those paths onto a two-level Russian rubric.

Rules
-----
* ``PARENTS`` / ``CHILDREN`` are the only public names.  Nothing here is
  copied from a competitor's marketing copy.
* ``RULES`` is ordered: the first regular expression matching the whole source
  path wins, so specific rules stay above generic ones.  Short transliterated
  stems are anchored with ``(?:^|[/-])`` so that ``shhit`` never matches
  ``zashhita``.
* ``OVERRIDES`` pins paths that keywords would misplace.
* ``classify_path`` returns a child slug or ``None`` for
  ``(no-source-category)``.  Anything not recognised lands in
  "Прочее оборудование" instead of being dropped.
* ``classify_unbranded`` applies the narrow, auditable model-prefix rules that
  the task allows for D-Link and Eltex records without a source category.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Two-level rubric
# --------------------------------------------------------------------------

PARENTS: list[tuple[str, str]] = [
    ("low-voltage", "Низковольтное оборудование"),
    ("switchgear", "Шкафы, щиты и корпуса"),
    ("automation", "Промышленная автоматизация"),
    ("drives", "Приводы и двигатели"),
    ("power", "Питание и защита"),
    ("metering", "Измерительные приборы и учёт"),
    ("cable", "Кабельные системы и монтаж"),
    ("wiring", "Электроустановочные изделия"),
    ("lighting", "Освещение"),
    ("network", "Сетевое и телекоммуникационное оборудование"),
    ("components", "Электронные компоненты"),
    ("tooling", "Инструмент, крепёж и расходники"),
    ("other", "Прочее оборудование"),
]

CHILDREN: list[tuple[str, str, str]] = [
    # slug, parent, public title
    ("lv-breakers", "low-voltage", "Автоматические выключатели"),
    ("lv-rcd", "low-voltage", "УЗО и дифавтоматы"),
    ("lv-switches", "low-voltage", "Рубильники и выключатели нагрузки"),
    ("lv-contactors", "low-voltage", "Контакторы и пускатели"),
    ("lv-relays", "low-voltage", "Реле"),
    ("lv-fuses", "low-voltage", "Предохранители"),
    ("lv-terminals", "low-voltage", "Клеммы и клеммные блоки"),
    ("lv-control", "low-voltage", "Кнопки и сигнальная арматура"),
    ("lv-busbar", "low-voltage", "Шинопроводы и сборные шины"),
    ("lv-connectors", "low-voltage", "Силовые и промышленные разъёмы"),
    ("lv-accessories", "low-voltage", "Аксессуары и комплектующие"),
    ("lv-other", "low-voltage", "Прочее низковольтное оборудование"),
    ("sg-cabinets", "switchgear", "Шкафы и корпуса"),
    ("sg-distribution", "switchgear", "Распределительные щиты"),
    ("sg-small", "switchgear", "Боксы и малые щиты"),
    ("sg-it", "switchgear", "IT-шкафы и стойки"),
    ("sg-parts", "switchgear", "Комплектующие щитов и шкафов"),
    ("sg-accessories", "switchgear", "Аксессуары для шкафов"),
    ("au-plc", "automation", "ПЛК и контроллеры"),
    ("au-io", "automation", "Модули ввода-вывода"),
    ("au-hmi", "automation", "Панели оператора"),
    ("au-sensors", "automation", "Датчики и энкодеры"),
    ("au-software", "automation", "ПО и конфигурирование"),
    ("au-pc", "automation", "Промышленные компьютеры"),
    ("au-psx", "automation", "Платформа PSX"),
    ("au-building", "automation", "Автоматизация зданий"),
    ("au-other", "automation", "Прочая автоматизация"),
    ("dr-motors", "drives", "Электродвигатели"),
    ("dr-vfd", "drives", "Частотные преобразователи"),
    ("dr-servo", "drives", "Сервоприводы и управление движением"),
    ("dr-gear", "drives", "Приводная техника"),
    ("dr-hydraulics", "drives", "Гидравлика и пневматика"),
    ("dr-accessories", "drives", "Аксессуары приводов"),
    ("pw-ups", "power", "ИБП"),
    ("pw-supplies", "power", "Блоки питания и распределение"),
    ("pw-stabilizers", "power", "Стабилизаторы и преобразователи"),
    ("pw-spd", "power", "УЗИП и молниезащита"),
    ("pw-grounding", "power", "Заземление"),
    ("pw-batteries", "power", "Аккумуляторы и зарядные устройства"),
    ("pw-ev", "power", "Зарядные станции"),
    ("pw-reactive", "power", "Компенсация реактивной мощности"),
    ("pw-transformers", "power", "Трансформаторы"),
    ("mt-kip", "metering", "КИП общего назначения"),
    ("mt-meters", "metering", "Счётчики электроэнергии"),
    ("mt-ct", "metering", "Трансформаторы тока"),
    ("mt-tools", "metering", "Измерительные приборы и тестеры"),
    ("mt-accessories", "metering", "Комплектующие для измерений"),
    ("cb-trays", "cable", "Лотки и кабеленесущие системы"),
    ("cb-conduits", "cable", "Трубы и каналы"),
    ("cb-lugs", "cable", "Наконечники и гильзы"),
    ("cb-entries", "cable", "Кабельные вводы"),
    ("cb-fasteners", "cable", "Хомуты и крепёж"),
    ("cb-wires", "cable", "Провода и кабели"),
    ("cb-marking", "cable", "Маркировка"),
    ("cb-accessories", "cable", "Прочие кабельные аксессуары"),
    ("wr-sockets", "wiring", "Розетки и вилки"),
    ("wr-switches", "wiring", "Выключатели и переключатели"),
    ("wr-frames", "wiring", "Рамки и панели"),
    ("wr-boxes", "wiring", "Установочные коробки"),
    ("wr-modules", "wiring", "Механизмы и модули"),
    ("wr-accessories", "wiring", "Аксессуары"),
    ("li-luminaires", "lighting", "Светильники"),
    ("li-lamps", "lighting", "Лампы и светодиоды"),
    ("li-emergency", "lighting", "Аварийное освещение"),
    ("li-decor", "lighting", "Декоративная светотехника"),
    ("li-accessories", "lighting", "Аксессуары освещения"),
    ("nw-switches", "network", "Коммутаторы"),
    ("nw-routers", "network", "Маршрутизаторы"),
    ("nw-wifi", "network", "Точки доступа Wi-Fi"),
    ("nw-cctv", "network", "Видеонаблюдение"),
    ("nw-voip", "network", "IP-телефония"),
    ("nw-media", "network", "Медиаконвертеры и оптика"),
    ("nw-cables", "network", "Патч-корды и кабельные сборки"),
    ("nw-power", "network", "Сетевое питание"),
    ("nw-other", "network", "Прочее сетевое оборудование"),
    ("cp-ic", "components", "Микросхемы"),
    ("cp-discrete", "components", "Транзисторы, диоды, оптроны"),
    ("cp-passive", "components", "Конденсаторы и резисторы"),
    ("cp-led", "components", "Светодиоды и индикаторы"),
    ("cp-connectors", "components", "Разъёмы и соединители"),
    ("cp-other", "components", "Прочие компоненты"),
    ("tl-hand", "tooling", "Ручной инструмент"),
    ("tl-power", "tooling", "Электроинструмент и станки"),
    ("tl-welding", "tooling", "Сварка и пайка"),
    ("tl-fasteners", "tooling", "Крепёж"),
    ("tl-chemicals", "tooling", "Химия и покрытия"),
    ("tl-consumables", "tooling", "Расходные материалы"),
    ("tl-safety", "tooling", "Средства защиты"),
    ("tl-spares", "tooling", "Запчасти"),
    ("ot-misc", "other", "Без уточнённой рубрики"),
    ("ot-legacy", "other", "Устаревшее оборудование"),
]

PARENT_BY_CHILD = {child: parent for child, parent, _ in CHILDREN}
TITLE_BY_CHILD = {child: title for child, _, title in CHILDREN}
TITLE_BY_PARENT = dict(PARENTS)
CHILDREN_BY_PARENT: dict[str, list[str]] = {slug: [] for slug, _ in PARENTS}
for _child, _parent, _title in CHILDREN:
    CHILDREN_BY_PARENT[_parent].append(_child)

FALLBACK_CHILD = "ot-misc"
NO_SOURCE = "(no-source-category)"

# --------------------------------------------------------------------------
# Ordered path rules (first match wins)
# --------------------------------------------------------------------------

RULES: list[tuple[str, str]] = [
    # === Литые корпуса раньше «шкафов» ====================================
    (r"apparaty-v-litom-korpuse|litom-korpuse", "lv-breakers"),

    # === Шкафы, щиты, корпуса ============================================
    (r"shkafy-i-stojki-dlya-it|aksessuary-dlya-it-shkafov|korpusa-stojki-i-aksessuary", "sg-it"),
    (r"pvp-optimalnaya/aksessuary-dvernye|funkczionalnye-obolochki|"
     r"zapasnye-chasti-dlya-universalnyx-shkafov|klyuch-dlya-shkafa", "sg-accessories"),
    (r"dverpanel|bokovayazadnyaya-panel|perednyaya-panel-raspredelitelnogo|verxnyaya-kryshka|"
     r"czokolelement|profil-raspredelitelnogo|kryshka-dlya-raspredelitelnogo|okno-raspredelitelnogo|"
     r"razdelitelnaya-peregorodka|panel-dlya-raspredelitelnogo|osnovanie-nizkovolt|raspredelitelnyj-modul|"
     r"komponent-dlya-|montazhnye-aksessuary|komplektuyushhie-dlya-malogo|ustrojstvo-podogreva|"
     r"termostat-raspredelitelnogo|svetilnik-dlya-raspredelitelnogo|glavnyj-vyklyuchatel|"
     r"shina-zazemleniya|derzhatel-support|din-rejka", "sg-parts"),
    (r"(?:^|[/-])shkafy-i-shhity|(?:^|[/-])shkafnaya-produkcziya|(?:^|[/-])napolnye-shkafy|"
     r"korpus-shkafa-pustoj|korpus-s-predoxranitelnym|korpus-adapter", "sg-cabinets"),
    (r"raspredelitelnyj-shkaf-pustoj|shhity-i-korpusa-metallicheskie|(?:^|[/-])shhity(?:[/-]|$)", "sg-distribution"),
    (r"malyj-raspredelitelnyj|shhitboks|shhity-i-boksy|korpusa-korobki-i-futlyary", "sg-small"),
    (r"(?:^|[/-])shkaf|(?:^|[/-])korpus|(?:^|[/-])stojk", "sg-cabinets"),

    # === Низковольтное оборудование ======================================
    # защита раньше выключателей
    (r"differenczialnogo-toka|difavtomat|ustrojstva-differenczialnoj|ustrojstvo-zashhitnogo-otklyucheniya", "lv-rcd"),
    (r"modulnyj-avtomaticheskij|modulnye-avtomaticheskie|modulnye-ustrojstva|avtomaticheskij-vyklyuchatel|"
     r"avtomaticheskie-vyklyuchateli|vozdushnye-avtomaticheskie|zashhity-transform|zashhity-dvigatelya|"
     r"promyshlennye-vyklyuchateli|easypact-ezc|ritejl-proektnaya/acti9", "lv-breakers"),
    (r"rubilnik|vyklyuchateli-nagruzki|vyklyuchatel-razedinitel|vyklyuchateli-razediniteli|"
     r"kommutaczionnoe-oborudovanie(?!-bloki)|perednyaya-chast-selektornogo|selektornyj-pereklyuchatel|"
     r"rukoyatka-dlya-vyklyuchatelej", "lv-switches"),
    (r"teplovye-rele|rele-peregruzki|rele-dlya-kontaktorov|(?:^|[/-])rele(?:[/-]|$)|"
     r"promezhutochnoe|impulsnoe|rele-kontrolya", "lv-relays"),
    (r"kontaktor|puskatel|tesys-[dfkg]|tesys-v|etvs|pusko-reguliruyushhee", "lv-contactors"),
    (r"predoxranitel|plavkaya-vstavka|(?:^|[/-])fuses", "lv-fuses"),
    (r"(?:^|[/-])klemm|klemmniki|terminal|zazhimy", "lv-terminals"),
    (r"knopk|nakladka-dlya-vyklyuchatelej|svetosignalnyj|ustrojstva-podachi-komand|stojka-signalnaya|"
     r"signalnoj-kolony|osnovanie-stojka|lampa-indikatornaya|kolpacheklinza|tekstovaya-opoznavatelnaya|"
     r"derzhatel-markirovki|svetovoj-opticheskij|akusticheskij-modul|indikator-srabatyvaniya|"
     r"stanczii-upravleniya|pribory-upravleniya-i-signalizaczii|svetovye-kolonny|upravlyayushhij-pereklyuchatel|"
     r"pereklyuchateli(?:[/-]|$)|elementy-upravleniya-i-indikatory|posty-upravleniya|"
     r"perednyaya-chast-indikatornoj|aktory|komplektuyushhie-dlya-ustrojstv-upravleniya", "lv-control"),
    (r"shinoprovod|sbornaya-shina|fazovaya-shina|shinoderzhatel|perexodnik-dlya-shin|"
     r"komplektuyushhie-dlya-sbornyx-shin|kanal-sbornoj-shiny|shinnyj-soedinitel|canalis-", "lv-busbar"),
    (r"(?:^|[/-])razemy|vilka-kabelnaya|kruglye-soediniteli", "lv-connectors"),
    (r"aksessuary-dlya-nizkovoltnogo|aksessuary-dlya-panelej-upravleniya|dopolnitelnyj-kontakt|"
     r"blok-vspomogatelnyx-kontaktov|katushka-dlya|indikatory-osnovaniya|komplekt-provodki|"
     r"nakladkavstavkamexanizm|zapasnye-chasti-nvo|shuntovojnezavisimyj|ezc-opczii|nsx-opczii|tesys-b-opczii|"
     r"prinadlezhnosti-dlya-montazha|drugie-akssesuary|aksessuary-vyklyuchatelej|"
     r"(?:^|[/-])aksessuary(?:[/-]|$)|aksessuary-i-komplektuyushhie|elektricheskie-prinadlezhnosti|"
     r"dopolnitelnoe-oborudovanie|rukoyatka-raspredelitelnyx|dekraft/", "lv-accessories"),
    (r"^nizkovoltnoe-oborudovanie$|^elektrotexnicheskaya-produkcziya$", "lv-other"),

    # === Приводы и двигатели =============================================
    (r"altivar|chastotno-reguliruemye|preobrazovateli-chastoty|low-voltage-ac-drives|"
     r"nizkovoltnye-privody-peremennogo-toka", "dr-vfd"),
    (r"servoprivod|servodvigatel|upravlenie-dvizheniem-i-robototexnika", "dr-servo"),
    (r"elektricheskie-dvigateli|asinxronnye|(?:^|[/-])dvigateli(?:[/-]|$)|avtomatizacziya-i-elektrodvigateli", "dr-motors"),
    (r"gidravlika|pnevmatika|(?:^|[/-])klapany|(?:^|[/-])truboprovody", "dr-hydraulics"),
    (r"pusk-i-zashhita-dvigatelya|upravlenie-dvigatelem|service-support|aksessuary-i-opczii-dlya-pch", "dr-accessories"),
    (r"^privody-i-dvigateli|^privodnaya-texnika|(?:^|[/-])privoda(?:[/-]|$)", "dr-gear"),

    # === Питание и защита ================================================
    (r"^ibp|ibp-dlya|thalassa", "pw-ups"),
    (r"bloki-pitaniya|elementy-i-ustrojstva-elektropitaniya|prinadlezhnosti-dlya-istochnika|pilotnye-ustrojstva", "pw-supplies"),
    (r"stabilizator|preobrazovateli-peremennogo|preobrazovateli-postoyannogo", "pw-stabilizers"),
    (r"perenapryazheniya|uzip|razryadnik|ogranichitel-perenapryazheniya", "pw-spd"),
    (r"molniezashhita|zazemlenie", "pw-grounding"),
    (r"akkumulyator|zaryadnye-ustrojstva", "pw-batteries"),
    (r"zaryadnye-stanczii|zaryadki-elektromobilej|zaryadnyx-stanczij", "pw-ev"),
    (r"kompensacziya-reaktivnoj|energoeffektivnost|ukrm", "pw-reactive"),
    (r"^transformatory$|^transformers$|aksessuary-dlya-transformerov", "pw-transformers"),

    # === Измерительные приборы ===========================================
    (r"schetchik|schyotchik", "mt-meters"),
    (r"transformator-toka|transformatory-toka|izmeritelnye-transformatory", "mt-ct"),
    (r"kontrolno-izmeritelnye-pribory|(?:^|[/-])kip(?:[/-]|$)|voltmetr|ampermetr|pereklyuchatel-voltmetra|"
     r"manometr|termometr", "mt-kip"),
    (r"izmeritelnye-pribory-i-testery|mnogofunkczionalnye-pribory|mnogofunkczionalnyj", "mt-tools"),
    (r"aksessuary-dlya-sredstv-izmereniya|komplektuyushhie-dlya-vstraivaemyx", "mt-accessories"),

    # === Кабельные системы ===============================================
    (r"lotk|lestnicz|kabel-kanaly|provolochnye-lotki|kabelenesushhie", "cb-trays"),
    (r"nakonechniki-i-gilzy|kabelnye-nakonechniki|(?:^|[/-])gilza", "cb-lugs"),
    (r"kabelnye-vvody", "cb-entries"),
    (r"xomuty|styazhk|kabelnye-xomuty|krepezhnye-detali", "cb-fasteners"),
    (r"^kabeli$|kabelnye-sborki|(?:^|[/-])provod", "cb-wires"),
    (r"markirovka", "cb-marking"),
    (r"termousadochnye|upravlenie-kabelem|izolenta|(?:^|[/-])kabel", "cb-accessories"),

    # === Электроустановочные изделия =====================================
    (r"ramki|ramka", "wr-frames"),
    (r"ritejl-optimalnaya/mexanicheskie|ritejl-ekonom/mexanicheskie|ritejl-optimalnaya/elektronnye|"
     r"ritejl-ekonom/elektronnye|ritejl-optimalnaya/telekommunik|ritejl-ekonom/telekommunik|"
     r"ritejl-optimalnaya/mini-kanaly|ritejl-optimalnaya/napolnye-lyuchki|ritejl-optimalnaya/pratika|"
     r"ritejl-optimalnaya/eui|installation-products|installyaczionnye-pribory/ustrojstvo-dlya-podklyucheniya|"
     r"dimmer-svetoregulyator|vstavka-lampa-podsvetki", "wr-modules"),
    (r"ritejl-ekonom/korobki|ritejl-optimalnaya/korobki|korobki-ustanovochnye", "wr-boxes"),
    (r"rozetk|schuko|blok-kombinirovannyj", "wr-sockets"),
    (r"vyklyuchatel-pereklyuchatel|zhalyuzijnyj", "wr-switches"),
    (r"ritejl-ekonom/szhimy|ritejl-ekonom/korobki-raspredelitelnye|ritejl-optimalnaya/domovoj|"
     r"aksessuary-dlya-elektroustanovochnyx|razemy-i-komponenty-dlya-vilok", "wr-accessories"),
    (r"^ritejl|elektroustanovochnye-izdeliya", "wr-modules"),

    # === Освещение =======================================================
    (r"avarijn|ukazateli-avarijnogo|osveshhenie-pereborki|nizhnee-osveshhenie", "li-emergency"),
    (r"svetodiod|lampy-i-trubki|(?:^|[/-])lampy|led-fonari|pereklyuchateli-yarkosti", "li-lamps"),
    (r"dekorativnaya|osvetitelnaya-texnika|osvetitelnye-aksessuary|vtorichnaya-optika|optoelektronnye", "li-decor"),
    (r"svetotexnika|osveshhenie|podsvetka", "li-luminaires"),

    # === Сетевое оборудование ============================================
    (r"actassi|patch-kord|kabelnye-sbory|(?:^|[/-])sks", "nw-cables"),
    (r"videonablyudeniya|pelco", "nw-cctv"),
    (r"telekommunikaczionnoe|promyshlennaya-kommunikacziya|(?:^|[/-])setev", "nw-other"),

    # === Промышленная автоматизация ======================================
    (r"platforma-avtomatizaczii-psx", "au-psx"),
    (r"moduli-vvoda|moduli-io|moduli-vizualnogo", "au-io"),
    (r"datchik|enkoder|(?:^|[/-])sensor|konczevoj|rele-davleniya|sledyashhix-sistem|tajmery|"
     r"komponenty-avtomatizaczii/(?!aksessuary|knopki|modulnye-knopki|posty|svetovye)", "au-sensors"),
    (r"plc/|plk-i-sistemy-upravleniya|programmiruemye-logicheskie|kontrollery-proczessov|"
     r"platforma-avtomatizaczii-msx|(?:^|[/-])kontrollery(?:[/-]|$)|kontrollery-i-oborudovanie-oem", "au-plc"),
    (r"panelnye-displei|chmi|dialogovye-paneli|indikatory-i-displei", "au-hmi"),
    (r"programmnoe-obespechenie", "au-software"),
    (r"promyshlennye-kompyutery|promyshlennye-pk|vstroennye-resheniya|periferijnye-ustrojstva|kompyuternye-produkty", "au-pc"),
    (r"sistemy-upravleniya-komfortom|sistemy-upravleniya-zdaniem|knx|eib|freehome|"
     r"mikroklimata|climasys|termoregulyator|termostat|avtomaticheskaya-signalizacziya|"
     r"aktivatory|aktor-", "au-building"),
    (r"^promyshlennaya-avtomatizacziya|^avtomatizacziya|(?:^|[/-])avtomatika", "au-other"),

    # === Электронные компоненты ==========================================
    (r"mikrosxemy|importnye-radiodetali|integralnye", "cp-ic"),
    (r"tranzistory|diody|optrony|tiristory", "cp-discrete"),
    (r"kondensatory|rezistory|potencziometry|termistory|varistory|rezonatory|(?:^|[/-])pamyat", "cp-passive"),
    (r"svetodiody", "cp-led"),
    (r"(?:^|[/-])razemy$|soediniteli", "cp-connectors"),
    (r"(?:^|[/-])komponenty$|pruzhiny|(?:^|[/-])zummer|induktivnye", "cp-other"),

    # === Инструмент, крепёж, расходники ==================================
    (r"svarka|payalnye", "tl-welding"),
    (r"elektroinstrument|stanok", "tl-power"),
    (r"instrument", "tl-hand"),
    (r"kraski|pokrytiya|germetiki|klei|ximicheskie|chistyashhie|zalivochnye|obezzhirivatel", "tl-chemicals"),
    (r"krepezh|metizy|bolt|gajk|shajb|samorez|dyubel|anker", "tl-fasteners"),
    (r"lichnaya-zashhita|bezopasnost|sredstva-zashhity", "tl-safety"),
    (r"zapchasti|zapasnye-chasti|detali-mashin", "tl-spares"),
    (r"izolenta|materialy-dlya-montazha|raskhodnye|rashodnye|(?:^|[/-])lenta$|skotch", "tl-consumables"),

    # === Заведомо неклассифицируемое =====================================
    (r"ustarevshee-oborudovanie", "ot-legacy"),
]

COMPILED = [(re.compile(pattern, re.IGNORECASE), child) for pattern, child in RULES]

# Paths the keyword rules would misplace; checked before every rule.
OVERRIDES: dict[str, str] = {
    "kondensatory/chip-kondensatory": "cp-passive",
    "kondensatory": "cp-passive",
    "transformator-toka": "mt-ct",
    "transformatory-toka": "mt-ct",
    "izmeritelnye-transformatory": "mt-ct",
    "transformatory": "pw-transformers",
    "transformers": "pw-transformers",
    "kabelnye-xomuty-i-montazhnyj-instrument": "cb-fasteners",
    "krepezhnye-detali-i-prisposobleniya": "tl-fasteners",
    "izolenta": "tl-consumables",
    "markirovka": "cb-marking",
    "osvetitelnye-aksessuary": "li-accessories",
    "osveshhenie-pereborki": "li-emergency",
    "nizhnee-osveshhenie": "li-emergency",
    "dekorativnaya-svetotexnika": "li-decor",
    "lampy": "li-lamps",
    "lampy-i-trubki": "li-lamps",
    "perednyaya-chast-indikatornoj-lampy": "lv-control",
    "svetodiody-vidimogo-spektra": "cp-led",
    "svetodiody-cob": "cp-led",
    "svetodiody-vysokoj-yarkosti": "cp-led",
    "optoelektronnye-pribory/osvetitelnaya-texnika": "li-decor",
    "vtorichnaya-optika": "li-accessories",
    "importnye-radiodetali/samsung-em": "cp-ic",
    "pamyat": "cp-passive",
    "razemy": "lv-connectors",
    "razemy-silovye": "lv-connectors",
    "razemy-i-komponenty-dlya-vilok-i-rozetok": "wr-accessories",
    "razemy-i-kabeli-dlya-zaryadki-elektromobilej": "pw-ev",
    "kruglye-soediniteli-i-komponenty": "cp-connectors",
    "knopki": "lv-control",
    "puskateli": "lv-contactors",
    "rele-davleniya": "au-sensors",
    "rele": "lv-relays",
    "kontrollery": "au-plc",
    "sensors": "au-sensors",
    "privoda": "dr-gear",
    "privodnaya-texnika": "dr-gear",
    "servoprivody": "dr-servo",
    "servodvigateli": "dr-servo",
    "servoprivody/servoprivody": "dr-servo",
    "servoprivody/kompaktnye-servoprivody": "dr-servo",
    "gidravlika-i-nasosy": "dr-hydraulics",
    "pnevmatika": "dr-hydraulics",
    "truboprovody": "dr-hydraulics",
    "programmnoe-obespechenie": "au-software",
    "dokumentacziya": "ot-misc",
    "raznoe": "ot-misc",
    "prochee": "ot-misc",
    "ne-klassificzirovano/ne-klassificzirovano": "ot-misc",
    "materialy-dlya-montazha": "tl-consumables",
    "telekommunikaczionnoe-oborudovanie": "nw-other",
    "promyshlennaya-kommunikacziya": "nw-other",
    "it-field-services/ne-vxodit-v-kompolitiku": "ot-misc",
    "promyshlennost-i-strojploshhadka": "ot-misc",
    "ustarevshee-oborudovanie-industry/ustarevshee-oborudovanie-industry": "ot-legacy",
    "ustarevshee-oborudovanie-ecob/ustarevshee-oborudovanie-ecob": "ot-legacy",
    "kommutaczionnoe-oborudovanie": "lv-switches",
    "kommutaczionnoe-rele": "lv-relays",
    "kommutaczionnoe-oborudovanie-bloki-pitaniya": "pw-supplies",
    "panelnye-displei-i-kontrolno-izmeritelnye-pribory": "au-hmi",
    "elementy-upravleniya-i-indikatory": "lv-control",
    "elementy-pitaniya-i-zaryadnye-ustrojstva": "pw-batteries",
    "ustrojstva-zashhity": "pw-spd",
    "ustrojstva-zashhity-ot-perenapryazheniya": "pw-spd",
    "ustrojstva-zashhity-ot-perenapryazheniya-dlya-okonechnogo-oborudovaniya": "pw-spd",
    "ustrojstva-zashhity-ot-perenapryazheniya-dlya-sistem-energosnabzheniya": "pw-spd",
    "zashhita-ot-perenapryazheniya": "pw-spd",
    "kombinirovannyj-razryadnik-dlya-sistem-energosnabzheniya": "pw-spd",
    "zashhita-czepi-i-nagruzki/avtomaticheskie-vyklyuchateli-i-ustrojstva-zashhity-czepej": "lv-breakers",
    "pusk-i-zashhita-dvigatelya/rele": "lv-relays",
    "pusk-i-zashhita-dvigatelya/kontaktory": "lv-contactors",
    "pusk-i-zashhita-dvigatelya/zashhita-dvigatelya": "dr-accessories",
    "pusk-i-zashhita-dvigatelya/preobrazovatel-chastoty": "dr-vfd",
    "upravlenie-dvigatelem/magnitnye-kontaktory": "lv-contactors",
    "upravlenie-dvigatelem/rele-peregruzki": "lv-relays",
    "upravlenie-dvigatelem/zashhitnye-ustrojstva-dlya-elektrodvigatelej": "dr-accessories",
    "privody-i-dvigateli/low-voltage-ac-drives": "dr-vfd",
    "privody-i-dvigateli/nizkovoltnye-privody-peremennogo-toka": "dr-vfd",
    "privody-i-dvigateli/privody": "dr-gear",
    "privody-i-dvigateli/dvigateli": "dr-motors",
    "privody-i-dvigateli/service-support": "dr-accessories",
    "privodnaya-texnika/altivar-312": "dr-vfd",
    "privodnaya-texnika/altivar-71-0-90-kvt": "dr-vfd",
    "privodnaya-texnika/aksessuary-i-opczii-dlya-pch-i-upp": "dr-accessories",
    "platforma-avtomatizaczii-psx/vychisliteli-rasxoda-realfo": "au-psx",
    "platforma-avtomatizaczii-psx/accutech": "au-psx",
    "platforma-avtomatizaczii-psx/scadapack-std": "au-psx",
    "platforma-avtomatizaczii-psx/scadapack-e": "au-psx",
    "platforma-avtomatizaczii-psx/plk-modicon-premium": "au-psx",
    "platforma-avtomatizaczii-psx/plk-modicon-quantum": "au-psx",
    "platforma-avtomatizaczii-psx/plk-micro": "au-psx",
    "platforma-avtomatizaczii-psx/plk-modicon-momentum": "au-psx",
    "platforma-avtomatizaczii-psx/modicon-x80": "au-psx",
    "platforma-avtomatizaczii-psx/po-unity-pro": "au-psx",
    "platforma-avtomatizaczii-psx/po-dlya-konfiguraczii": "au-psx",
    "platforma-avtomatizaczii-psx/prochie-setevye-komponenty": "au-psx",
    "platforma-avtomatizaczii-psx/aksessuary-dlya-promyshlennyx-kompyuterov": "au-psx",
    "platforma-avtomatizaczii-msx/plk-twido": "au-plc",
    "platforma-avtomatizaczii-msx/oborudovanie-bezopasnosti": "au-plc",
    "platforma-avtomatizaczii-msx/moduli-io-tm5tm7-i-aksessuary": "au-io",
    "plc/passivnye-infrakrasnye-datchiki-dvizheniya-poverxnostnogo-montazha": "au-sensors",
    "sistemy-upravleniya-komfortom/ssl-kontrollery": "au-building",
    "sistemy-upravleniya-komfortom/ssl-aksessuary": "au-building",
    "sistemy-upravleniya-komfortom/ssl-shlyuzy": "au-building",
    "sistemy-upravleniya-komfortom/ssl-datchiki": "au-building",
    "sistemy-upravleniya-komfortom/knx-system-d-interfejsy-upravleniya": "au-building",
    "sistemy-upravleniya-komfortom/knx-system-m-interfejsy-upravleniya": "au-building",
    "sistemy-upravleniya-zdaniem/periferoborudovanie-dlya-sistavtomzd": "au-building",
    "vstroennye-resheniya/moduli-vizualnogo-vyvoda": "au-hmi",
    "vstroennye-resheniya/instrumentalnye-sredstva": "au-pc",
    "actassi-sks/actassi-mednye-komponenty-sks": "nw-cables",
    "patch-kordy": "nw-cables",
    "kabelnye-sborki": "nw-cables",
    "shkafy-i-shhity": "sg-cabinets",
    "raspredelitelnyj-shkaf-pustoj": "sg-distribution",
    "korpus-shkafa-pustoj": "sg-cabinets",
    "kabelnye-vvody": "cb-entries",
    "shina-zazemleniya-dlya-raspredelitelnogo-shhita": "sg-parts",
    "sistemy-videonablyudeniya/gibridnye-sistemy-videonablyudeniya-pelco": "nw-cctv",
    "komponenty-avtomatizaczii/aksessuary-dlya-knopok-i-lampochek": "lv-control",
    "komponenty-avtomatizaczii/posty-upravleniya-plastikovye": "lv-control",
    "komponenty-avtomatizaczii/tajmery": "au-other",
    "komponenty-avtomatizaczii/svetovye-kolonny-xvb": "lv-control",
    "komponenty-avtomatizaczii/modulnye-knopki-i-lampochki-diametrom-22": "lv-control",
    "komponenty-avtomatizaczii/knopki-i-lampochki-diametrom-30-mm": "lv-control",
    "akssesuary-dlya-avarijnogo-osveshheniya": "li-emergency",
    "avarijnye-svetilniki": "li-emergency",
    "ukazateli-avarijnogo-vyxoda": "li-emergency",
    "led-fonari": "li-luminaires",
    "domovoj-zvukovaya-signalizacziya": "wr-accessories",
    "ritejl-optimalnaya/stojki-mini-kolonny-rozetbloki": "wr-modules",
    "nakladka-dlya-vyklyuchatelej-dimmerov-zhalyuzijnyx-pereklyuchatelej-tajmerov": "wr-modules",
    "kabelnye-nakonechniki-klemmniki-i-klemmy": "cb-lugs",
    "termousadochnye-trubki": "cb-accessories",
    "promyshlennaya-avtomatizacziya/moduli-vvoda-i-vyvoda": "au-io",
    "promyshlennaya-avtomatizacziya/kabeli": "cb-wires",
    "instrumenty-elektroinstrumenty-i-stanki": "tl-power",
    "rasxodnye-materialy-dlya-kompyuterov": "tl-consumables",
    "elektrotexnicheskaya-produkcziya": "lv-other",
    "nizkovoltnoe-oborudovanie": "lv-other",
    "nizkovoltnoe-oborudovanie/modulnye-ustrojstva": "lv-breakers",
    "nizkovoltnoe-oborudovanie/installation-products": "wr-modules",
    "nizkovoltnoe-oborudovanie/avtomatizacziya-freehome": "au-building",
    "nizkovoltnoe-oborudovanie/intellektualnye-installyaczionnye-sistemy-eibknx": "au-building",
    "vyklyuchatel-pereklyuchatel": "wr-switches",
    "pereklyuchateli": "lv-control",
    "dimmer-svetoregulyator": "wr-modules",
    "klapany": "dr-hydraulics",
    "din-rejka-s-profilem": "sg-parts",
    "pvp-optimalnaya/canalis-ks": "lv-busbar",
    "pvp-optimalnaya/canalis-kb": "lv-busbar",
    "avtomaticheskaya-signalizacziya": "au-building",
    "aktor-upravleniya-nagrevom-dlya-informaczionnoj-shiny": "au-building",
    "aktor-pereklyuchatel-dlya-informaczionnoj-shiny": "au-building",
    "pvp-optimalnaya/thalassa-pls": "pw-ups",
    "pvp-medium/easypact-ezc": "lv-breakers",
    "servis/kontrollery-i-oborudovanie-oem": "au-plc",
    "blok-kombinirovannyj-kombinacziya-vyklyuchatelya-i-rozetok": "wr-sockets",
    "aksessuary-dlya-transformerov-raznoe": "pw-transformers",
    "installyaczionnye-pribory/ustrojstvo-dlya-podklyucheniya": "wr-modules",
    "pereklyuchateli-yarkosti": "li-accessories",
    "ustrojstvo-zashhitnogo-otklyucheniya-uzo-vyklyuchatel-differenczialnogo-toka-vdt": "lv-rcd",
    "avtomaticheskij-vyklyuchatel-differenczialnogo-toka-difavtomat-avdt": "lv-rcd",
    "ustrojstva-differenczialnoj-zashhity": "lv-rcd",
    "installyaczionnye-pribory/ustrojstvo-zashhitnogo-otklyucheniya": "lv-rcd",
    "installyaczionnye-pribory/differenczialnyj-avtomaticheskij-vyklyuchatel": "lv-rcd",
    "selektornyj-pereklyuchatel-v-sbore": "lv-switches",
    "perednyaya-chast-selektornogo-mnogopoziczionnogo-pereklyuchatelya": "lv-switches",
    "pvp-medium/etvs-tor-teplovye-rele-peregruzki": "lv-relays",
    "pvp-optimalnaya/tesys-tor-d-teplovye-rele-peregruzki": "lv-relays",
    "pvp-optimalnaya/tesys-tor-k-teplovye-rele-peregruzki": "lv-relays",
    "pvp-optimalnaya/tesys-eor-d-elektronnye-rele-peregruzki": "lv-relays",
    "pvp-optimalnaya/tesys-aux-promezhutochnye-rele": "lv-relays",
    "pvp-optimalnaya/tesys-k-promezhutochnye-rele": "lv-relays",
    "rele-dlya-kontaktorov": "lv-relays",
    "kombinirovannyj-puskatel-elektrodvigatelya": "lv-contactors",
    "magnitnyj-puskatelkontaktor-peremen-toka-ac": "lv-contactors",
    "kontaktornyj-blok-puskatel-kombinirovannyj": "lv-contactors",
    "zapasnye-chasti-nvo/pusko-reguliruyushhee-oborudovanie": "lv-contactors",
    "zapasnye-chasti-nvo/silovye-avtomaticheskie-vyklyuchateli": "lv-breakers",
    "silovye-avtomaticheskie-vyklyuchateli/vyklyuchateli": "lv-breakers",
    "silovye-avtomaticheskie-vyklyuchateli/zashhita-vyklyuchatelej": "lv-accessories",
    "pribory-upravleniya-i-signalizaczii/zashhita-vyklyuchatelej": "lv-accessories",
    "installyaczionnye-pribory/ogranichitel-perenapryazheniya": "pw-spd",
    "installyaczionnye-pribory/avtomaticheskij-vyklyuchatel": "lv-breakers",
    "installyaczionnye-pribory/rele": "lv-relays",
    "ritejl-optimalnaya/korobki-altira": "wr-boxes",
    "datchiki-i-pereklyuchateli": "au-sensors",
    "konczevoj-vyklyuchatel": "au-sensors",
    "promezhutochnoe-rele": "lv-relays",
    "impulsnoe-rele": "lv-relays",
    "rele-kontrolya-i-upravleniya": "lv-relays",
    "nakladkavstavkamexanizm-dlya-kommunikaczionnyx-ustrojstv": "lv-accessories",
    "upravlenie-kabelem": "cb-accessories",
    "osvetitelnaya-texnika": "li-decor",
    "dopolnitelnoe-oborudovanie-dlya-sledyashhix-sistem": "au-sensors",
    "soedinitelnye-instrumenty-i-aksessuary": "tl-hand",
    "zapchasti-dlya-bytovoj-texniki": "tl-spares",
    "zapchasti-dlya-smartfonov": "tl-spares",
    "zapchasti-dlya-noutbukov": "tl-spares",
    "zapchasti-dlya-planshetov": "tl-spares",
    "zapasnye-chasti-dlya-remonta": "tl-spares",
    "detali-mashin": "tl-spares",
    "bezopasnost-mashiny-i-operatora": "tl-safety",
    "lichnaya-zashhita-i-bezopasnost": "tl-safety",
    "pilotnye-ustrojstva": "pw-supplies",
    "kompyuternye-produkty": "au-pc",
    "promyshlennye-vyklyuchateli": "lv-breakers",
    "shuntovojnezavisimyj-rasczepitel-dlya-silovogo-vyklyuchatelya": "lv-accessories",
    "upravlyayushhij-pereklyuchatelkomandokontroller": "lv-control",
    "dopolnitelnoe-oborudovanie": "lv-accessories",
    "komplektuyushhie-dlya-ustrojstv-upravleniya-i-signalizaczii": "lv-control",
    "pvp-medium/ezc-opczii-i-aksessuary": "lv-accessories",
    "pvp-optimalnaya/nsx-opczii-i-aksessuary": "lv-accessories",
    "pvp-optimalnaya/tesys-b-opczii-i-aksessuary": "lv-accessories",
    "pvp-optimalnaya/prinadlezhnosti-dlya-montazha": "lv-accessories",
    "pvp-optimalnaya/drugie-akssesuary": "lv-accessories",
    "pvp-proektnaya/aksessuary-vyklyuchatelej-630-6300": "lv-accessories",
    "dekraft/bazovaya-funkcziya": "lv-accessories",
    "dekraft/aksessuar": "lv-accessories",
    "pvp-optimalnaya/climasys-dt-klimaticheskie-registratory": "au-building",
    "derzhatel-support-montazhnyj-element-dlya-modulnyx-eui": "sg-parts",
    "aksessuary-dlya-elektroustanovochnyx-izdelij": "wr-accessories",
    "aksessuary-dlya-zaryadnyx-stanczij": "pw-ev",
    "aksessuary-dlya-zaryadnyx-stanczij-ev": "pw-ev",
    "vstavka-lampa-podsvetki-dlya-elektroustanovochnyx-izdelij": "wr-modules",
    "termoregulyator-komnatnyj-termostat": "au-building",
    "kabelnye-lestniczy-i-lotki-wibestago/kabelnye-lotki-wibe-aksessuary": "cb-trays",
    "kabelnye-lestniczy-i-lotki-wibestago/aksessuary-wibe-obshhie": "cb-trays",
    "kabelnye-lestniczy-i-lotki-wibestago/kabelnye-lestniczy-wibe-aksessuary": "cb-trays",
    "kabelnye-lestniczy-i-lotki-wibestago/kabelnye-lotki-wibe": "cb-trays",
    "kabelnye-lestniczy-i-lotki-wibestago/kabelnye-lestniczy-wibe": "cb-trays",
    "flanecz-panel-plata-kabelnogo-vvoda-dlya-raspredelitelnyx-shhitovshkafov": "sg-parts",
    "komponenty-avtomatizaczii/kulachkovye-pereklyuchateli": "au-sensors",
    "stojka-signalnaya-ustrojstvo-svetovoj-signalizaczii-v-sbore": "lv-control",
    "svetovoj-opticheskij-modul-dlya-signalnoj-stojki": "lv-control",
    "osnovanie-stojka-signalnoj-kolonny-bez-truby": "lv-control",
    "korpusa-korobki-i-futlyary": "sg-small",
    "korpus-adapter-dlya-otkrytogonakladnogo-montazha-eui-skrytoj-ustanovki": "wr-modules",
    "pvp-optimalnaya/akssesuary-dvernye": "sg-accessories",
    "montazhnaya-sistema-dlya-kanala-raspredelitelnoj-shiny": "lv-busbar",
    "montazhnaya-plastina-dlya-raspredelitelnogo-shhita": "sg-parts",
    "nizkovoltnoe-oborudovanie/cable-distribution-cabinets": "sg-cabinets",
    "raspredelitelnye-korobki": "wr-boxes",
}

# --------------------------------------------------------------------------
# Rubrication of records without a source category
# --------------------------------------------------------------------------

NETWORK_BRANDS = {
    "d-link", "dlink", "eltex", "qtech", "q-tech", "dssl", "nag",
    "cisco", "huawei", "tp-link", "mikrotik", "zyxel", "juniper", "aruba",
}

_PREFIX_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(des|dgs|dxs|dss|dls|dws|dqs|mps|mes|mvr)[\s\-]?\d", re.I), "nw-switches"),
    (re.compile(r"^(dir|dwr|dfr|dsr|esr)[\s\-]?\d", re.I), "nw-routers"),
    (re.compile(r"^(dap|dwl|wep|wlc)[\s\-]?\d", re.I), "nw-wifi"),
    (re.compile(r"^(dcs|dnr|dvn|dvh|ds-2)[\s\-]?\d", re.I), "nw-cctv"),
    (re.compile(r"^(dph|dpn|tau|smg|ntu|vg)[\s\-]?\d", re.I), "nw-voip"),
    (re.compile(r"^(dem|dmc|dfe|dme|sfp|rg)[\s\-]?\d", re.I), "nw-media"),
    (re.compile(r"^(dps|dpa|das|dpd)[\s\-]?\d", re.I), "nw-power"),
]

_WORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bкоммутатор", re.I), "nw-switches"),
    (re.compile(r"\bмаршрутизатор", re.I), "nw-routers"),
    (re.compile(r"(точк[аи] доступа|wi-?fi|беспроводн)", re.I), "nw-wifi"),
    (re.compile(r"(ip-?камер|видеонаблюден|видеорегистратор)", re.I), "nw-cctv"),
    (re.compile(r"(ip-?телефон|voip|шлюз)", re.I), "nw-voip"),
    (re.compile(r"(медиаконвертер|оптическ|sfp)", re.I), "nw-media"),
    (re.compile(r"(патч-?корд|патчкорт)", re.I), "nw-cables"),
    (re.compile(r"(poe|блок питания|инжектор)", re.I), "nw-power"),
]


def normalize_path(path: str) -> str:
    return path.strip().strip("/").lower()


def classify_path(path: str) -> str | None:
    """Map a source category path to a child slug.

    Returns ``None`` for ``(no-source-category)`` so the caller can apply
    brand/model rules instead.  Never raises: unknown paths land in
    "Прочее оборудование".
    """
    key = normalize_path(path)
    if not key or key == NO_SOURCE:
        return None
    if key in OVERRIDES:
        return OVERRIDES[key]
    for pattern, child in COMPILED:
        if pattern.search(key):
            return child
    return FALLBACK_CHILD


# Filled by ``load_known_paths`` so tests and the builder can agree on what
# the audit actually contained.
_KNOWN_PATHS: set[str] = set()


def load_known_paths(paths) -> None:
    global _KNOWN_PATHS
    _KNOWN_PATHS = {normalize_path(item) for item in paths}


def is_known_path(path: str) -> bool:
    return normalize_path(path) in _KNOWN_PATHS


def classify_unbranded(brand: str, name: str, mpn: str, description: str) -> tuple[str, str]:
    """Classify a record that has no source category.

    Returns ``(child_slug, reason)``; the reason is stored only in the
    internal audit table and never exposed by the API.
    """
    brand_key = (brand or "").strip().lower()
    if brand_key in NETWORK_BRANDS:
        head = f"{mpn or ''} {name or ''}".strip()
        for pattern, child in _PREFIX_RULES:
            if pattern.search(head):
                return child, "net-prefix"
        text = " ".join(filter(None, (name or "", description or "")))
        for pattern, child in _WORD_RULES:
            if pattern.search(text):
                return child, "net-word"
        return "nw-other", "net-fallback"
    # Conservative technical nouns for records whose original rubric is absent.
    patterns = [
        (r'дифавтомат|дифференциальн.{0,25}(выключател|автомат)|\bузо\b', 'lv-rcd'),
        (r'автоматическ.{0,25}выключател|выключател.{0,25}автомат', 'lv-breakers'),
        (r'частотн.{0,20}преобразоват', 'dr-vfd'),
        (r'электродвигател|шпиндельн.{0,20}(двигател|пакет)', 'dr-motors'),
        (r'сервопривод|серводвигател|сервоконтроллер', 'dr-servo'),
        (r'контактор|магнитн.{0,15}пускател', 'lv-contactors'),
        (r'\bреле\b', 'lv-relays'),
        (r'\bкнопк|сигнальн.{0,20}(арматур|ламп|колон)', 'lv-control'),
        (r'клемм|клеммн', 'lv-terminals'),
        (r'предохранител', 'lv-fuses'),
        (r'\bрозетк|\bвилк', 'wr-sockets'),
        (r'светильник', 'li-luminaires'),
        (r'\bламп|светодиодн.{0,15}лент', 'li-lamps'),
        (r'кабельн.{0,25}(ввод|сальник)', 'cb-entries'),
        (r'наконечник|\bгильз', 'cb-lugs'),
        (r'\bлот[ок]|кабеленесущ|кабельн.{0,20}лестниц', 'cb-trays'),
        (r'гофрир.{0,20}труб|труб.{0,20}гофр|кабель.канал|металлорукав', 'cb-conduits'),
        (r'держател.{0,15}кабел|кабельн.{0,15}хомут', 'cb-fasteners'),
        (r'\bболт|\bгайк|\bшайб|\bвинт|\bанкер|\bшпильк|\bсаморез', 'tl-fasteners'),
        (r'\bшкаф|распределительн.{0,15}щит', 'sg-cabinets'),
        (r'\bкоробк.{0,20}(распред|установ)|\bбокс', 'wr-boxes'),
        (r'блок.{0,10}питания|источник.{0,15}питания', 'pw-supplies'),
        (r'гигростат|термостат', 'au-building'),
        (r'\bдатчик|\bэнкодер', 'au-sensors'),
        (r'модуль.{0,20}(ввод|вывод|преобразован)|контроллер', 'au-io'),
        (r'выключател|рубильник|разъединител', 'lv-switches'),
    ]
    for text in [name or '', (description or '')[:500]]:
        for pattern, child in patterns:
            if re.search(pattern, text, re.I):
                return child, 'technical-noun'
    if brand_key in {'dkc', 'км-профиль', 'obo bettermann', 'промрукав', 'система км', 'соэми ст.оскол'}:
        if re.search(r'консол|страт.профил|кронштейн|кабель|combitech|зажим балочн', name + ' ' + description[:300], re.I):
            return 'cb-accessories', 'cable-mounting-context'
    return FALLBACK_CHILD, "no-category"


@dataclass(frozen=True)
class Rubric:
    parent: str
    child: str

    @property
    def parent_title(self) -> str:
        return TITLE_BY_PARENT[self.parent]

    @property
    def child_title(self) -> str:
        return TITLE_BY_CHILD[self.child]


def rubric_for(child: str) -> Rubric:
    parent = PARENT_BY_CHILD.get(child, "other")
    return Rubric(parent=parent, child=child)
