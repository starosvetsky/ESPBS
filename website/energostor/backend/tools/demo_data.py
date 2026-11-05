"""Generate a small demo catalog for local preview (not used in production).

    python tools/demo_data.py

Creates ``data/demo-source/batches/*.sqlite3`` and builds ``data/catalog.sqlite3``.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from espbs_catalog.store import build  # noqa: E402
from fixtures import make_batch, product  # noqa: E402

AD = (" – артикул товара бренда {brand} с розничной ценой 12 400 ₽ за штуку. "
      "Купите по специальной цене оптом или в розницу в компании Олписа. "
      "Купить можно по телефону +7 (812) 000-00-00 или отправить заявку на почту info@example.ru.")

ITEMS = [
    ("Выключатель автоматический 3P 63 А, 6 кА", "Schneider Electric", "A9F04363",
     "nizkovoltnoe-oborudovanie/modulnyj-avtomaticheskij-vyklyuchatel-avtomat",
     "Выключатель автоматический 3P 63 А, характеристика C, 6 кА.",
     {"Номинальный ток": "63 А", "Число полюсов": "3", "Характеристика": "C"}),
    ("Дифавтомат 2P 32 А, 30 мА", "Schneider Electric", "A9R72232",
     "avtomaticheskij-vyklyuchatel-differenczialnogo-toka-difavtomat-avdt",
     "Дифференциальный автомат 2P 32 А, 30 мА, тип AC.",
     {"Номинальный ток": "32 А", "Ток утечки": "30 мА"}),
    ("Контактор 3P 40 А 220 В", "Schneider Electric", "LC1D40M7",
     "kontaktory-i-puskateli", "Контактор переменного тока, 3 полюса, 40 А, катушка 220 В.",
     {"Номинальный ток": "40 А", "Напряжение катушки": "220 В"}),
    ("Реле промежуточное 24 В DC", "Schneider Electric", "RXM2AB2BD",
     "rele", "Реле промежуточное 2 переключающих контакта, 24 В DC.",
     {"Напряжение": "24 В", "Контактов": "2"}),
    ("Клемма винтовая 2.5 мм² серая", "Phoenix Contact", "UT 2,5",
     "klemmy-na-din-rejku", "Клемма винтовая на DIN-рейку, 2.5 мм², 24 А.",
     {"Сечение": "2.5 мм²", "Цвет": "серый"}),
    ("Кнопка пуска зелёная 22 мм", "Schneider Electric", "XB4BA31",
     "knopka-knopochnyj-vyklyuchatel", "Кнопка без фиксации, зелёная, диаметр 22 мм.",
     {"Диаметр": "22 мм", "Цвет": "зелёный"}),
    ("Лампа сигнальная 230 В красная", "Schneider Electric", "XB4BVM4",
     "svetosignalnyj-blok-s-lampoderzhatelem-patronom-dlya-ustrojstv-czepej-upravleniya",
     "Лампа индикаторная 230 В, красная.", {"Напряжение": "230 В"}),
    ("Щит распределительный IP54, 24 модуля", "IEK", "ЩРН-24 IP54",
     "raspredelitelnyj-shkaf-pustoj", "Щит навесной металлический, 24 модуля, IP54.",
     {"Модулей": "24", "Степень защиты": "IP54"}),
    ("Шкаф напольный 42U 800×800", "DKC", "R5-42U-88",
     "napolnye-shkafy-i-korpusa", "Шкаф телекоммуникационный напольный, 42U, 800×800.",
     {"Высота": "42U"}),
    ("ПЛК Modicon M221, 16 DI/8 DO", "Schneider Electric", "TM221CE16R",
     "plk-i-sistemy-upravleniya", "Контроллер логический, 16 дискретных входов, 8 реле.",
     {"Входов": "16", "Выходов": "8"}),
    ("Модуль дискретного ввода 16 каналов", "Schneider Electric", "TM3DI16",
     "platforma-avtomatizaczii-msx/moduli-io-tm5tm7-i-aksessuary",
     "Модуль ввода 16 каналов, 24 В DC.", {"Каналов": "16"}),
    ("Панель оператора 7 дюймов, Ethernet", "Schneider Electric", "HMIGXU3512",
     "panelnye-displei-i-kontrolno-izmeritelnye-pribory",
     "Панель оператора 7 дюймов, Ethernet, 2 последовательных порта.", {"Диагональ": "7"}),
    ("Датчик индуктивный M18 PNP", "Turck", "BI5-M18-AP6X",
     "komponenty-avtomatizaczii/induktivnye-datchiki",
     "Датчик индуктивный M18, 5 мм, PNP, кабель 2 м.", {"Диаметр": "M18"}),
    ("Преобразователь частоты 5.5 кВт", "Schneider Electric", "ATV312HU55N4",
     "chastotno-reguliruemye-preobrazovateli",
     "Преобразователь частоты 5.5 кВт, 380 В, IP20.", {"Мощность": "5.5 кВт"}),
    ("Электродвигатель 5.5 кВт 1500 об/мин", "WEG", "W22-5.5-4",
     "asinxronnye-elektricheskie-dvigateli",
     "Двигатель асинхронный 5.5 кВт, 1500 об/мин, 380 В, IM1081.",
     {"Мощность": "5.5 кВт", "Обороты": "1500 об/мин"}),
    ("ИБП онлайн 3000 ВА, 2U", "APC", "SRT3000XLI",
     "ibp", "ИБП онлайн двойного преобразования 3000 ВА, 2U.",
     {"Мощность": "3000 ВА"}),
    ("Кабель ВВГнг-LS 3×2.5", "Кабель-СПб", "ВВГнг-LS 3х2.5",
     "kabelnye-sborki", "Кабель силовой ВВГнг-LS 3×2.5, бухта 100 м.", {"Жил": "3"}),
    ("Лоток лестничный 300×80, 3 м", "DKC", "LSL-300-80",
     "kabelnye-lestniczy-i-lotki-wibestago/kabelnye-lestniczy-wibe",
     "Лоток лестничный 300×80 мм, длина 3 м, горячее цинкование.", {"Ширина": "300 мм"}),
    ("Наконечник кабельный ТМЛ 25-10", "КВТ", "ТМЛ 25-10",
     "nakonechniki-i-gilzy", "Наконечник лужёный под опрессовку, 25 мм², отверстие 10 мм.",
     {"Сечение": "25 мм²"}),
    ("Светильник LED 40 Вт IP65", "Световые технологии", "LWP-40",
     "ritejl-optimalnaya/avarijnye-svetilniki", "Светильник светодиодный 40 Вт, 5000 К, IP65.",
     {"Мощность": "40 Вт"}),
    ("Розетка 1-местная с з/к, белая", "Schneider Electric", "MZ520127",
     "ritejl-optimalnaya/mexanicheskie-funkczii", "Розетка скрытой установки с заземлением.",
     {"Цвет": "белый"}),
    ("Рамка 2-постовая, белая", "Schneider Electric", "MZ522302",
     "ritejl-optimalnaya/ramki-belyj", "Рамка для двух механизмов, белая.", {"Постов": "2"}),
    ("Счётчик трёхфазный, 1 тариф", "Энергомера", "CE308",
     "schyotchik-elektroenergii", "Счётчик трёхфазный прямого включения, 1 тариф.",
     {"Тарифов": "1"}),
    ("Трансформатор тока 300/5 А", "IEK", "Т-0.66 300/5",
     "transformatory-toka", "Трансформатор тока 300/5 А, класс 0.5.", {"Класс": "0.5"}),
    ("Мультиметр цифровой True RMS", "Fluke", "117",
     "mnogofunkczionalnyj-izmeritelnyj-pribor", "Мультиметр True RMS с бесконтактным детектором.",
     {"True RMS": "да"}),
    ("Ограничитель перенапряжения 1P+N", "Schneider Electric", "A9L15692",
     "ustrojstva-zashhity-ot-perenapryazheniya", "УЗИП тип 2, 1P+N, 20 кА.",
     {"Тип": "2", "Ток": "20 кА"}),
    ("Коммутатор 24 порта Gigabit", "D-Link", "DGS-1210-28",
     "dlink", "Коммутатор управляемый, 24 порта 10/100/1000, 4 SFP.",
     {"Портов": "24"}),
    ("Маршрутизатор с Wi-Fi 6", "D-Link", "DIR-X1560",
     "dlink", "Маршрутизатор AX1500, 4 порта LAN, Wi-Fi 6.", {}),
    ("Точка доступа Wi-Fi 6 корпоративная", "Eltex", "WEP-2ac",
     "eltex", "Точка доступа WEP-2ac, 2 радиомодуля, PoE.", {"Стандарт": "802.11ac"}),
    ("Шлюз VoIP Eltex", "Eltex", "TAU-8",
     "eltex", "Шлюз TAU-8, 8 FXS портов.", {}),
    ("Микросхема драйвер MOSFET", "Texas Instruments", "UCC27517",
     "mikrosxemy", "Драйвер затвора MOSFET, 4 А, SOT-23-5.", {}),
    ("Конденсатор электролитический 470 мкФ 25 В", "Jamicon", "470uF/25V",
     "kondensatory", "Конденсатор электролитический 470 мкФ, 25 В, 105 °C.", {}),
    ("Опрессовочные клещи 10–120 мм²", "КВТ", "ПК-120",
     "instrumenty-ruchnye-i-dlya-obrabotki", "Клещи гидравлические для наконечников 10–120 мм².",
     {}),
    ("Изолента ПВХ 19 мм × 20 м", "3M", "Temflex 165",
     "izolenta", "Лента изоляционная ПВХ 19 мм × 20 м, чёрная.", {}),
    ("Лампа светодиодная E27 10 Вт 4000 К", "Osram", "LED-E27-10",
     "lampy", "Лампа LED 10 Вт, цоколь E27, 4000 К, 1055 лм.", {}),
    ("Гофра ПВХ 20 мм с зондом", "DKC", "ГПВХ-20",
     "truboprovody", "Труба гофрированная ПВХ 20 мм, с протяжкой, 50 м.", {}),
    ("Пускатель магнитный 25 А 380 В", "IEK", "КМИ-22530",
     "magnitnyj-puskatelkontaktor-peremen-toka-ac", "Пускатель магнитный 25 А, катушка 380 В.",
     {}),
    ("Предохранитель плавкий 63 А", "ETI", "CH10x38-63",
     "predoxraniteli-vstavki-plavkie", "Вставка плавкая цилиндрическая 10×38, 63 А, gG.", {}),
    ("Разъём промышленный 16 А 3P+E", "Mennekes", "TYP-1351",
     "silovye-i-promyshlennye-razemy", "Разъём силовой 16 А, 3P+E, IP44.", {}),
    ("Светильник аварийный с аккумулятором", "Световые технологии", "L-EMS-30",
     "ritejl-optimalnaya/avarijnye-svetilniki", "Светильник аварийный 30 Вт, автономность 3 ч.",
     {}),
]

NEW_ITEMS = [
    ("Контактор 4P 25 А", "Schneider Electric", "LC1DT25M7", "kontaktory-i-puskateli",
     "Контактор 4P 25 А, катушка 220 В.", {"Номинальный ток": "25 А"}),
    ("Реле контроля напряжения", "IEK", "УЗМ-51МД", "rele-kontrolya-i-upravleniya",
     "Реле контроля напряжения трёхфазное.", {}),
]


def payload(item):
    name, brand, mpn, path, description, attributes = item
    return product(
        name,
        brand=brand,
        mpn=mpn,
        url=f"https://olnisa.ru/manufacturers/x/{path}/",
        description=description + AD.format(brand=brand),
        attributes=attributes,
    )


def main() -> int:
    source = ROOT / "data" / "demo-source"
    batches = source / "batches"
    batches.mkdir(parents=True, exist_ok=True)
    for path in batches.glob("*.sqlite3"):
        path.unlink()

    first = [{"payload": payload(item), "collected_at": "2026-03-01T09:00:00Z"} for item in ITEMS]
    make_batch(batches / "2026-03.sqlite3", first, "2026-03-01T00:00:00+00:00")

    second = []
    for item in ITEMS[:8]:
        row = payload(item)
        row["description"] = row.get("description", "") + " Поставка со склада в Санкт-Петербурге."
        second.append({"payload": row, "collected_at": "2026-05-01T09:00:00Z"})
    for item in NEW_ITEMS:
        second.append({"payload": payload(item), "collected_at": "2026-05-01T09:00:00Z"})
    make_batch(batches / "2026-05.sqlite3", second, "2026-05-01T00:00:00+00:00")

    dest = ROOT / "data" / "catalog.sqlite3"
    stats = build(source, dest, log=None)
    with sqlite3.connect(dest) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    print(
        f"demo catalog: records={stats.raw_records} products={meta['unique_products']} "
        f"updated={stats.updated} -> {dest}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
