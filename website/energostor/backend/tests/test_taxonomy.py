"""Рубрикация: все 505 исходных путей получают понятный раздел."""

from __future__ import annotations

import unittest
from collections import Counter

from tests import ROOT  # noqa: F401
from espbs_catalog import data, taxonomy as tx

NO_SOURCE = "(no-source-category)"


class RubricStructureTestCase(unittest.TestCase):
    def test_parents_and_children_are_consistent(self):
        parents = [slug for slug, _ in tx.PARENTS]
        self.assertEqual(len(parents), len(set(parents)), "дубли родителей")
        self.assertEqual(len(parents), len(tx.TITLE_BY_PARENT))
        for slug, title in tx.PARENTS:
            self.assertTrue(title.strip(), slug)
            self.assertTrue(tx.CHILDREN_BY_PARENT[slug], f"у раздела {slug} нет подразделов")

        child_slugs = [child for child, _, _ in tx.CHILDREN]
        self.assertEqual(len(child_slugs), len(set(child_slugs)), "дубли подразделов")
        for child, parent, title in tx.CHILDREN:
            self.assertIn(parent, parents, child)
            self.assertTrue(title.strip(), child)
            self.assertLessEqual(len(title), 60, child)

    def test_titles_are_unique_inside_a_parent(self):
        for parent, children in tx.CHILDREN_BY_PARENT.items():
            titles = [tx.TITLE_BY_CHILD[child] for child in children]
            duplicates = [t for t, n in Counter(titles).items() if n > 1]
            self.assertEqual(duplicates, [], f"{parent}: {duplicates}")

    def test_rubric_lookup(self):
        rubric = tx.rubric_for("lv-breakers")
        self.assertEqual(rubric.parent, "low-voltage")
        self.assertEqual(rubric.parent_title, "Низковольтное оборудование")
        self.assertEqual(rubric.child_title, "Автоматические выключатели")
        # неизвестный подраздел не должен ронять приложение
        self.assertEqual(tx.rubric_for("no-such-child").parent, "other")


class SourcePathCoverageTestCase(unittest.TestCase):
    def test_all_audited_paths_are_mapped(self):
        paths = [path for path, _ in data.source_paths()]
        self.assertEqual(len(paths), 505)
        self.assertEqual(len(set(paths)), 505, "аудит содержит повторы")

        unmapped = []
        for path in paths:
            child = tx.classify_path(path)
            if path == NO_SOURCE:
                self.assertIsNone(child)
                continue
            if child is None or child not in tx.TITLE_BY_CHILD:
                unmapped.append((path, child))
        self.assertEqual(unmapped, [], "пути без раздела")

    def test_known_paths_are_exactly_the_audited_ones(self):
        self.assertEqual(len(data.known_paths()), 505)
        self.assertIn("rele", data.known_paths())
        self.assertIn("nizkovoltnoe-oborudovanie/shkafnaya-produkcziya", data.known_paths())

    def test_only_expected_paths_land_in_other(self):
        leftovers = {
            path for path, _ in data.source_paths()
            if path != NO_SOURCE and tx.rubric_for(tx.classify_path(path)).parent == "other"
        }
        allowed_prefixes = ("raznoe", "prochee", "ne-klassificzirovano", "dokumentacziya",
                            "it-field-services", "promyshlennost-i-strojploshhadka")
        unexpected = [path for path in leftovers
                      if not path.startswith(allowed_prefixes)
                      and "ustarevshee" not in path]
        self.assertEqual(unexpected, [], "лишние пути в «Прочее оборудование»")

    def test_keyword_boundaries_do_not_confuse_zashchita_and_shchit(self):
        # «zashhita» не должен попадать в «шкафы» из-за подстроки shhit
        self.assertNotEqual(tx.rubric_for(tx.classify_path("zashhita-ot-perenapryazheniya")).parent,
                            "switchgear")
        self.assertEqual(tx.classify_path("zashhita-ot-perenapryazheniya"), "pw-spd")
        self.assertEqual(tx.classify_path("raspredelitelnyj-shkaf-pustoj"), "sg-distribution")
        self.assertEqual(tx.classify_path("shkafy-i-stojki-dlya-it-oborudovaniya"), "sg-it")

    def test_unknown_path_falls_back_to_other(self):
        self.assertEqual(tx.classify_path("some/unknown/section"), "ot-misc")
        # пустой путь и «(no-source-category)» — не рубрика, а её отсутствие:
        # дальше применяются правила по бренду и модели
        self.assertIsNone(tx.classify_path(""))
        self.assertIsNone(tx.classify_path("(no-source-category)"))


class UnbrandedRulesTestCase(unittest.TestCase):
    def test_dlink_prefixes(self):
        cases = {
            "DES-3200-28": "nw-switches",
            "DGS-1210-28": "nw-switches",
            "DIR-825": "nw-routers",
            "DAP-2660": "nw-wifi",
            "DCS-934L": "nw-cctv",
            "DPH-150S": "nw-voip",
            "DEM-310GT": "nw-media",
            "DPS-200": "nw-power",
        }
        for mpn, expected in cases.items():
            child, reason = tx.classify_unbranded("D-Link", "Оборудование " + mpn, mpn, "")
            self.assertEqual(child, expected, mpn)
            self.assertEqual(reason, "net-prefix")

    def test_eltex_prefixes(self):
        cases = {"MES2408": "nw-switches", "ESR-12": "nw-routers", "WEP-2ac": "nw-wifi",
                 "TAU-8": "nw-voip"}
        for mpn, expected in cases.items():
            child, _ = tx.classify_unbranded("Eltex", mpn, mpn, "")
            self.assertEqual(child, expected, mpn)

    def test_wording_rules_as_backup(self):
        child, reason = tx.classify_unbranded("D-Link", "Коммутатор управляемый", "X1", "")
        self.assertEqual((child, reason), ("nw-switches", "net-word"))
        child, reason = tx.classify_unbranded("D-Link", "Странный товар", "X2", "")
        self.assertEqual((child, reason), ("nw-other", "net-fallback"))

    def test_technical_name_recognized_without_source_category(self):
        child, reason = tx.classify_unbranded("Schneider Electric", "Выключатель", "A9F04116", "")
        self.assertEqual((child, reason), ("lv-switches", "technical-noun"))

    def test_empty_brand(self):
        self.assertEqual(tx.classify_unbranded("", "Товар", "", "")[0], "ot-misc")


if __name__ == "__main__":
    unittest.main()
