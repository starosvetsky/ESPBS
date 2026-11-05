"""Описания, ссылки и идентификаторы: гигиена публичных данных."""

from __future__ import annotations

import unittest

from tests import ROOT  # noqa: F401  (кладёт корень проекта в sys.path)
from espbs_catalog import textproc as tp

AD_TAIL = (
    " – артикул товара бренда Schneider Electric с розничной ценой 24 699 ₽ за штуку. "
    "Купите 33209 по специальной цене оптом или в розницу в компании Олписа. "
    "Специальная цена распространяется на всю продукцию для наших постоянных клиентов. "
    "Купить 33209 Schneider Electric в Олписе оптом или в розницу можно по телефону, "
    "отправить заявку на почту или через сайт https://olnisa.ru/catalog/."
)


class DescriptionTestCase(unittest.TestCase):
    def test_advertising_tail_is_removed_technical_part_kept(self):
        raw = "КОМПЛЕКТ ИЗ ДВУХ ТРОСОВ 2,5 М ДЛЯ ВЗАИМОБЛОКИРОВКИ ВЫКЛЮЧАТЕЛЕЙ MASTERPACT 33209" + AD_TAIL
        cleaned = tp.clean_description(raw)
        self.assertIn("КОМПЛЕКТ ИЗ ДВУХ ТРОСОВ 2,5 М", cleaned)
        for marker in ("артикул товара", "Олпис", "₽", "оптом", "по телефону", "olnisa"):
            self.assertNotIn(marker, cleaned, msg=f"остался маркер {marker!r}")

    def test_technical_specs_survive(self):
        raw = ("Выключатель автоматический 3P 63 А, характеристика C, 6 кА. "
               "Номинальное напряжение 400 В, степень защиты IP20." + AD_TAIL)
        cleaned = tp.clean_description(raw)
        self.assertIn("63 А", cleaned)
        self.assertIn("400 В", cleaned)
        self.assertIn("IP20", cleaned)
        self.assertNotIn("Купите", cleaned)

    def test_only_promo_text_becomes_empty(self):
        raw = "Купите по специальной цене в компании Олписа, звоните по телефону +7 (812) 000-00-00."
        self.assertEqual(tp.clean_description(raw), "")

    def test_phone_email_and_urls_removed(self):
        raw = ("Кабель силовой 3×2.5, бухта 100 м. "
               "Звоните +7 (812) 111-22-33, пишите sales@example.ru, "
               "подробности на www.example.ru/cable.")
        cleaned = tp.clean_description(raw)
        self.assertIn("Кабель силовой", cleaned)
        for marker in ("+7", "sales@", "www.", "example.ru"):
            self.assertNotIn(marker, cleaned)

    def test_price_sentence_removed_but_specs_kept(self):
        raw = "Контактор 40 А, катушка 220 В. Цена 12 000 ₽ за штуку."
        cleaned = tp.clean_description(raw)
        self.assertIn("40 А", cleaned)
        self.assertNotIn("12 000", cleaned)
        self.assertNotIn("₽", cleaned)

    def test_none_and_empty_are_safe(self):
        self.assertEqual(tp.clean_description(None), "")
        self.assertEqual(tp.clean_description("   "), "")
        self.assertEqual(tp.clean_description({"unexpected": 1}), "")


class UrlTestCase(unittest.TestCase):
    def test_plain_https_is_allowed(self):
        url = tp.valid_public_url("https://cdn.example.org/img/a.jpg")
        self.assertEqual(url, "https://cdn.example.org/img/a.jpg")

    def test_fragment_is_dropped_query_kept(self):
        url = tp.valid_public_url("https://cdn.example.org/img/a.jpg?x=1#frag")
        self.assertEqual(url, "https://cdn.example.org/img/a.jpg?x=1")

    def test_dangerous_schemes_rejected(self):
        for bad in ("javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd",
                    "ftp://example.org/a.jpg", "//example.org/x.jpg"):
            self.assertIsNone(tp.valid_public_url(bad), msg=bad)

    def test_credentials_rejected(self):
        self.assertIsNone(tp.valid_public_url("https://user:pass@example.org/a.jpg"))

    def test_garbage_rejected(self):
        for bad in (None, "", 42, ["https://example.org"], "https://"):
            self.assertIsNone(tp.valid_public_url(bad))

    def test_olnisa_images_rejected_even_from_enrichment(self):
        self.assertTrue(tp.forbidden_host("olnisa.ru"))
        self.assertTrue(tp.forbidden_host("cdn.olnisa.ru"))
        self.assertFalse(tp.forbidden_host("notolnisa.ru"))
        images = tp.clean_images([
            "https://olnisa.ru/upload/1.jpg",
            "https://cdn.olnisa.ru/upload/2.jpg",
            "https://cdn.example.org/3.jpg",
            "javascript:alert(1)",
        ])
        self.assertEqual(images, ["https://cdn.example.org/3.jpg"])

    def test_images_are_deduplicated_and_capped(self):
        urls = [f"https://cdn.example.org/{i}.jpg" for i in range(30)]
        images = tp.clean_images(urls + urls)
        self.assertEqual(len(images), tp.IMAGES_LIMIT)
        self.assertEqual(len(set(images)), len(images))

    def test_documents_are_sanitised(self):
        docs = tp.clean_documents([
            {"name": "Паспорт", "url": "https://cdn.example.org/passport.pdf"},
            {"name": "Плохой", "url": "javascript:alert(1)"},
            {"name": "Олпис", "url": "https://olnisa.ru/file.pdf"},
            {"name": "", "url": "https://cdn.example.org/brochure.pdf"},
            "https://cdn.example.org/raw.pdf",
        ])
        self.assertEqual(docs, [
            {"name": "Паспорт", "url": "https://cdn.example.org/passport.pdf"},
            {"name": "brochure.pdf", "url": "https://cdn.example.org/brochure.pdf"},
        ])


class AttributeTestCase(unittest.TestCase):
    def test_values_are_joined_and_limits_applied(self):
        attrs = tp.clean_attributes({
            "Номинальный ток": ["16 А", "20 А"],
            "Пусто": "",
            "": "без названия",
            "Длинное": "x" * 900,
        })
        self.assertEqual(attrs[0], {"label": "Номинальный ток", "value": "16 А; 20 А"})
        self.assertNotIn("Пусто", [a["label"] for a in attrs])
        self.assertLessEqual(len(attrs[-1]["value"]), tp.ATTR_VALUE_LIMIT)

    def test_non_dict_returns_empty(self):
        self.assertEqual(tp.clean_attributes(None), [])
        self.assertEqual(tp.clean_attributes(["a"]), [])


class IdentityTestCase(unittest.TestCase):
    def test_seller_international_phone_and_html_removed(self):
        result=tp.clean_description('Производитель DKC. <br>Информацию о стоимости товара можно уточнить по телефону +375-44-775-32-57.')
        self.assertEqual(result,'Производитель DKC.')

    def test_dedupe_key_requires_both_parts(self):
        self.assertIsNotNone(tp.dedupe_key("Schneider Electric", "A9F04116"))
        self.assertIsNone(tp.dedupe_key("Schneider Electric", ""))
        self.assertIsNone(tp.dedupe_key("", "A9F04116"))
        self.assertIsNone(tp.dedupe_key("Brand", "—"))

    def test_dedupe_key_ignores_brand_case_but_preserves_mpn(self):
        a = tp.dedupe_key("Schneider Electric", "A9F04116")
        b = tp.dedupe_key(" schneider  electric ", " A9F04116 ")
        self.assertEqual(a, b)

    def test_dedupe_key_keeps_real_differences(self):
        self.assertNotEqual(tp.dedupe_key("Brand", "AB-100"), tp.dedupe_key("Brand", "AB-200"))

    def test_stable_product_ids(self):
        first = tp.product_id_for_key("brand|mpn")
        second = tp.product_id_for_key("brand|mpn")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertNotEqual(first, tp.product_id_for_record("brand|mpn"))

    def test_slugify_transliterates(self):
        self.assertEqual(tp.slugify("Шнайдер Электрик"), "shnayder-elektrik")
        self.assertEqual(tp.slugify("D-Link"), "d-link")
        self.assertEqual(tp.slugify("***", "brand"), "brand")

    def test_mpn_normalisation(self):
        self.assertEqual(tp.normalize_mpn("  a9f04116 "), "a9f04116")
        self.assertEqual(tp.normalize_mpn(None), "")


class CategoryPathTestCase(unittest.TestCase):
    KNOWN = {
        "nizkovoltnoe-oborudovanie",
        "nizkovoltnoe-oborudovanie/shkafnaya-produkcziya",
        "rele",
    }

    def test_longest_known_suffix_wins(self):
        url = "https://olnisa.ru/manufacturers/schneider/nizkovoltnoe-oborudovanie/shkafnaya-produkcziya/"
        self.assertEqual(
            tp.category_path_from_url(url, self.KNOWN),
            "nizkovoltnoe-oborudovanie/shkafnaya-produkcziya",
        )

    def test_partial_match_keeps_known_prefix(self):
        url = "https://example.org/catalog/rele/page-2/"
        self.assertEqual(tp.category_path_from_url(url, self.KNOWN), "rele")

    def test_unknown_url_falls_back_to_tail(self):
        url = "https://dlink.ru/ru/products/1/des-3200-28.html"
        self.assertEqual(tp.category_path_from_url(url, self.KNOWN), "1/des-3200-28.html")

    def test_empty_url(self):
        self.assertEqual(tp.category_path_from_url("", self.KNOWN), "")
        self.assertEqual(tp.category_path_from_url(None, self.KNOWN), "")


class TextTestCase(unittest.TestCase):
    def test_control_characters_and_spaces(self):
        self.assertEqual(tp.plain_text("a\x00b\n\nc   d"), "a b c d")

    def test_truncation(self):
        self.assertEqual(len(tp.plain_text("x" * 100, 10)), 10)

    def test_summary(self):
        summary = tp.short_summary("слово " * 100, 80)
        self.assertLessEqual(len(summary), 81)
        self.assertTrue(summary.endswith("…"))


if __name__ == "__main__":
    unittest.main()
