"""Serve a standalone local preview of the actual footer component."""
from pathlib import Path
import shutil
import sys

source=Path(__file__).parent
target=Path(sys.argv[1]).resolve()
target.mkdir(parents=True,exist_ok=True)
for name in ['footer.css','blueprint.css','blueprint.js']:
    shutil.copyfile(source/name,target/name)
shutil.copytree(source/'assets',target/'assets',dirs_exist_ok=True)
footer=(source/'footer.twig').read_text(encoding='utf-8').split('<dialog')[0]
footer=footer.replace("{% include 'catalog/view/template/common/blueprint.twig' %}",(source/'blueprint.twig').read_text(encoding='utf-8'))
footer=footer.replace('energostor-theme/assets/img/reference/','assets/')
html='''<!DOCTYPE html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Энергостор — проверка чертежа</title>
<link rel="stylesheet" href="footer.css"><link rel="stylesheet" href="blueprint.css">
<style>body{margin:0;font-family:Arial,sans-serif}main{height:110vh;background:#f5f5f5;padding:40px;box-sizing:border-box}h1{font-size:24px;font-weight:400}*{box-sizing:border-box}</style>
<body class="energostor-restored"><main><h1>Локальная проверка футера</h1><p>Прокрутите вниз: чертёж строится один раз.</p>'''+footer+'''<script src="blueprint.js" defer></script></body></html>'''
(target/'index.html').write_text(html,encoding='utf-8')
(target/'static.html').write_text(html.replace('<script src="blueprint.js" defer></script>',''),encoding='utf-8')
(target/'reduced.html').write_text(html.replace('<script src="blueprint.js" defer></script>','<script>var original=window.matchMedia;window.matchMedia=function(q){return q===\'(prefers-reduced-motion: reduce)\'?{matches:true}:original.call(window,q)};</script><script src="blueprint.js" defer></script>'),encoding='utf-8')
print(target)
