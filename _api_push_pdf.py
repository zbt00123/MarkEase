import base64
import json
import subprocess
import urllib.request


TOKEN = subprocess.check_output(['gh', 'auth', 'token'],
                                text=True).strip()
API = 'https://api.github.com'
REPO = '/repos/zbt00123/MarkEase'


def api(method, path, payload=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            'Authorization': 'Bearer ' + TOKEN,
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'MarkEase-CI-Push',
            'Content-Type': 'application/json',
        })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))


remote = api('GET', REPO + '/git/ref/heads/main')['object']['sha']
base_tree = api('GET', REPO + '/git/commits/' + remote)['tree']['sha']
print('remote', remote)

updated = [
    'app/platform/mac.py',
    'packaging/macos.spec',
    'web/js/app.js',
    'main.py',
    '.github/workflows/build.yml',
]
entries = []
for path in updated:
    data = open(path, 'rb').read()
    blob = api('POST', REPO + '/git/blobs', {
        'content': base64.b64encode(data).decode('ascii'),
        'encoding': 'base64',
    })
    entries.append({'path': path, 'mode': '100644',
                    'type': 'blob', 'sha': blob['sha']})
    print('update', path)

tree = api('POST', REPO + '/git/trees', {
    'base_tree': base_tree,
    'tree': entries,
})
commit = api('POST', REPO + '/git/commits', {
    'message': 'fix(mac): 修复双击 md 打开；PDF 原生打印分页/浅色/无高亮',
    'tree': tree['sha'],
    'parents': [remote],
})
api('PATCH', REPO + '/git/refs/heads/main', {
    'sha': commit['sha'],
    'force': False,
})
print('created', commit['sha'])
