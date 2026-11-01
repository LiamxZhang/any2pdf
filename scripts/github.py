"""Small maintainer API client; credentials stay in the environment or Git helper."""
import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request


def github_request(endpoint, method='GET', payload=None):
    if not endpoint.startswith('/') or endpoint.startswith('//'):
        raise ValueError('Use an API path beginning with /')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
            text=True, capture_output=True, timeout=20,
            env={**os.environ, 'GCM_INTERACTIVE': 'Never', 'GIT_TERMINAL_PROMPT': '0'})
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        token = fields.get('password')
    if not token:
        raise RuntimeError('Authenticate GitHub through Git Credential Manager or GITHUB_TOKEN.')
    req = urllib.request.Request('https://api.github.com' + endpoint,
        data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'Any2PDF-maintainer',
                 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else {}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('endpoint')
    parser.add_argument('--method', default='GET')
    parser.add_argument('--data', type=json.loads)
    args = parser.parse_args()
    try:
        print(json.dumps(github_request(args.endpoint, args.method, args.data), ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as exc:
        print(f'GitHub API HTTP {exc.code}: {exc.read().decode("utf-8", errors="replace")}')
        raise SystemExit(1)
