import re

s = open('main.py', encoding='utf-8').read()
m = re.search(r'script = r"""(.*?)"""', s, re.S)
if not m:
    raise SystemExit('no script')
open('_ui_test.js', 'w', encoding='utf-8').write(m.group(1))
print('extracted', len(m.group(1)))
