"""Report OpenCode/Tervik status without displaying the ingest credential."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def status(config_dir: Path) -> dict:
    config_path = Path(os.environ.get('TERVIK_OPENCODE_CONFIG', config_dir / 'tervik.json'))
    try:
        config = json.loads(config_path.read_text())
    except (OSError, ValueError):
        config = {}
    endpoint = os.environ.get('TERVIK_ENDPOINT') or config.get('endpoint') or 'http://127.0.0.1:8000'
    report = {
        'plugin_installed': (config_dir / 'plugins/tervik.js').is_file(),
        'key_configured': bool(os.environ.get('TERVIK_API_KEY') or config.get('apiKey')),
    }
    try:
        url = urlsplit(endpoint)
        if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError('invalid endpoint')
    except (ValueError, TypeError):
        report['verification'] = 'invalid_endpoint'
        return report
    report['endpoint'] = endpoint
    headers = {}
    # Never use the ingest key for dashboard administration.
    if os.environ.get('TERVIK_ADMIN_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['TERVIK_ADMIN_TOKEN']
    def get(path):
        with urlopen(Request(endpoint.rstrip('/') + path, headers=headers), timeout=5) as response:
            return json.load(response)
    try:
        report['health'] = get('/api/health').get('status')
        report['projects'] = []
        for project in get('/api/projects'):
            setup = get('/api/projects/' + project['id'] + '/setup')
            report['projects'].append({
                'id': project['id'], 'name': project['name'],
                'events_received': setup['events_received'],
                'conversations': setup['conversations'],
                'last_event_at': setup['last_event_at'],
                'jobs': setup['jobs'],
            })
        report['verification'] = 'reachable'
    except HTTPError as error:
        report['verification'] = 'dashboard_auth_required' if error.code in (401, 403) else 'http_error'
        report['http_status'] = error.code
        error.close()
    except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        report['verification'] = 'unavailable'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'opencode')
    args = parser.parse_args()
    print(json.dumps(status(args.config_dir), indent=2))
