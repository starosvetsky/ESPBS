"""Статический фронтенд: синтаксис JS, ссылки на ресурсы, запрещённые упоминания."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests import ROOT

FRONTEND = ROOT / "frontend"
ASSETS = FRONTEND / "assets" / "catalog"
PAGES = [FRONTEND / "catalog" / "index.html", FRONTEND / "brands" / "index.html"]
JS_FILES = sorted(ASSETS.glob("*.js"))


def find_node() -> str | None:
    for candidate in (
        shutil.which("node"),
        str(Path.home() / ".dsh" / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies"
            / "node" / "bin" / "node.exe"),
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class FrontendTestCase(unittest.TestCase):
    def test_pages_exist(self):
        for page in PAGES:
            self.assertTrue(page.is_file(), page)

    def test_js_files_exist(self):
        names = {path.name for path in JS_FILES}
        for expected in ("api.js", "menu.js", "catalog-page.js", "brands-page.js", "config.js"):
            self.assertIn(expected, names)

    def test_js_syntax_with_node(self):
        node = find_node()
        if not node:
            self.skipTest("node недоступен, синтаксическая проверка JS пропущена")
        for path in JS_FILES:
            with self.subTest(path.name):
                result = subprocess.run(
                    [node, "--check", str(path)],
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr[:800])

    def test_pages_reference_existing_assets(self):
        missing = []
        for page in PAGES:
            html = page.read_text(encoding="utf-8")
            for match in re.finditer(r'(?:src|href)="([^"]+)"', html):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                    continue
                cleaned = target.split("?")[0]
                resolved = (page.parent / cleaned).resolve()
                if not resolved.exists():
                    missing.append((page.name, cleaned))
        # Эти файлы живут в основном сайте (/energostor/...), а не в папке вёрстки.
        site_assets = ("../assets/img/", "../vendors/", "../")
        unexpected = [
            item for item in missing
            if not any(item[1].startswith(prefix) for prefix in site_assets)
        ]
        self.assertEqual(unexpected, [], "битые ссылки на ресурсы")

    def test_no_forbidden_mentions(self):
        forbidden = re.compile(r"(olnisa|мерлион|merlion|олпис)", re.IGNORECASE)
        offenders = []
        for path in FRONTEND.rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".js", ".css"}:
                continue
            if path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if forbidden.search(text):
                offenders.append(path.name)
        self.assertEqual(offenders, [], "упоминания источника в публичном фронтенде")

    def test_no_unsafe_dom_sinks(self):
        dangerous = re.compile(r"(eval\(|new Function\(|document\.write\(|\.outerHTML\s*=)")
        for path in JS_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(dangerous.search(text), msg=path.name)

    def test_html_is_inserted_with_textcontent(self):
        page_js = (ASSETS / "catalog-page.js").read_text(encoding="utf-8")
        # допускается только очистка через innerHTML = '' ; любой другой HTML — нет
        for match in re.finditer(r"\.innerHTML\s*=\s*([^;]+);", page_js):
            self.assertEqual(match.group(1).strip(), "''", msg="вставка HTML строкой")

    def test_menu_component_is_wired(self):
        for page in PAGES:
            html = page.read_text(encoding="utf-8")
            self.assertIn("data-catalog-menu", html)
            self.assertIn("menu.js", html)
            api_source = (ASSETS / "api.js").read_text(encoding="utf-8")
            self.assertIn("'/energostor/api/catalog'", api_source)
            self.assertIn("'/api/catalog'", api_source)

    def test_brands_page_links_to_catalog_with_brand_filter(self):
        text = (ASSETS / "brands-page.js").read_text(encoding="utf-8")
        self.assertIn("../catalog/?brand=", text)


if __name__ == "__main__":
    unittest.main()
