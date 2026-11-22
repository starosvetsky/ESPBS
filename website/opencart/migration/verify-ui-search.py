"""Read-only live search fixtures for the 2026-11-23 catalog snapshot."""

import importlib.util
import re
from urllib.parse import urlencode

spec = importlib.util.spec_from_file_location('ui_check','/opt/energostor-next/verify-ui.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [('D-Link',379),('Dlink',379),('D-Link DGS',119),('ABB DGS-1210',0),('_265236',1),('ZXZZNONEXISTENT50921',0)]
for query, expected in cases:
    status, html = module.fetch('/index.php?'+urlencode({'route':'product/search','search':query}))
    assert status==200,(query,status)
    match = re.search(r'ui-listing-toolbar"><p>\s*([\d\s]+)',html)
    count = int(re.sub(r'\D','',match[1])) if match else 0
    assert count==expected,(query,count,expected)
    assert 'Fatal error' not in html
    print(query, count, 'OK',flush=True)
print('Search fixtures passed for the 2026-11-23 release')
