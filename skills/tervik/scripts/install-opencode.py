"""Install the OpenCode adapter without placing an ingest key in command arguments."""

import argparse
import json
import os
from pathlib import Path
import shutil
import uuid


def install(config_dir: Path, endpoint: str | None = None, api_key: str | None = None) -> None:
    source = Path(__file__).resolve().parent
    adapter = config_dir / 'tervik'
    plugins = config_dir / 'plugins'
    adapter.mkdir(parents=True, exist_ok=True)
    plugins.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / 'tervik.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if endpoint:
        config['endpoint'] = endpoint
    if api_key:
        config['apiKey'] = api_key
    config.setdefault('userId', str(uuid.uuid4()))
    # Restrict permissions before writing, including when updating an existing file.
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(fd, 0o600)
        output.write(json.dumps(config, indent=2) + '\n')
    for name in ('opencode-plugin.mjs', 'tervik-client.mjs'):
        shutil.copy2(source / name, adapter / name)
    # Keep helpers outside plugins: OpenCode invokes all exports from plugin files.
    (plugins / 'tervik.js').write_text("export { default } from '../tervik/opencode-plugin.mjs';\n")
    print(f'Installed OpenCode plugin in {plugins / "tervik.js"}')
    print(f'Private configuration: {config_path}')
    if not (config.get('apiKey') or os.environ.get('TERVIK_API_KEY')):
        print('Configure the Tervik project key before restarting OpenCode. No events will be sent without it.')
    print('Restart OpenCode to load the plugin. Existing chat history is not exported.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'opencode')
    parser.add_argument('--endpoint', default=os.environ.get('TERVIK_ENDPOINT'))
    parser.add_argument('--api-key-env', default='TERVIK_API_KEY', help='Name of the environment variable containing the ingest key; never pass the key itself.')
    args = parser.parse_args()
    install(args.config_dir, args.endpoint, os.environ.get(args.api_key_env))
