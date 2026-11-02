"""Synthetic extraction checks; never contact live sites."""
import unittest
from scrapling_trial import extract


class ExtractionTests(unittest.TestCase):
    def test_scope_duplicates_and_required_fields(self):
        html = '''<div class="block-vendors">
        <a href="/vendors-and-solutions/test/"><img alt="Тест &amp; Co" src="/test.svg"></a>
        <a href="/vendors-and-solutions/test/"><img alt="Тест &amp; Co" src="/test.svg"></a>
        <a href="https://elsewhere.invalid/vendors-and-solutions/test/"><img alt="Wrong" src="/a.svg"></a>
        <a href="/vendors-and-solutions/test/product/"><img alt="Product" src="/a.svg"></a>
        <a href="/vendors-and-solutions/empty/"><img src="/a.svg"></a></div>
        <a href="/vendors-and-solutions/navigation/"><img alt="Navigation" src="/a.svg"></a>'''
        expected = [{'name': 'Тест & Co', 'profile_url': 'https://vad.merlion.ru/vendors-and-solutions/test/',
                     'logo_url': 'https://vad.merlion.ru/test.svg'}]
        for engine in ('bs4', 'scrapling'):
            self.assertEqual(extract(html, engine), expected)

    def test_conflicting_duplicate_rejected(self):
        html = '<div class="block-vendors">' + ''.join(
            f'<a href="/vendors-and-solutions/test/"><img alt="{name}" src="/a.svg"></a>'
            for name in ('One', 'Two')) + '</div>'
        for engine in ('bs4', 'scrapling'):
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                extract(html, engine)


if __name__ == '__main__':
    unittest.main()
