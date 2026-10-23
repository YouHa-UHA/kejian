#!/usr/bin/env python3
"""Stable protocol-1 entry point. Updates run before any business operation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


def load(path):
    # Execute the checked bytes, rather than an unrelated cached .pyc.
    source = path.read_bytes()
    spec = importlib.util.spec_from_file_location('kejian_runtime', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def active_runtime(config, bundled):
    config_data = json.loads(config.read_text(encoding='utf-8'))
    binding = hashlib.sha256(json.dumps({'apiBase': config_data['apiBase'].rstrip('/'),
        'connectionId': config_data['connectionId'],
        'credentialHash': hashlib.sha256(config_data['token'].encode()).hexdigest()},
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    state = config.resolve().parent / '.kejian' / binding
    try:
        pointer = json.loads((state / 'active-runtime.json').read_text())
        revision = pointer['sha256']
        if len(revision) != 64 or any(x not in '0123456789abcdef' for x in revision):
            raise ValueError()
        target = state / 'runtime' / (revision + '.py')
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != revision:
            raise ValueError()
        return target
    except (OSError, ValueError, KeyError, TypeError):
        return bundled


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config', required=True)
    args, _ = parser.parse_known_args()
    config = Path(args.config).resolve()
    bundled = Path(__file__).with_name('kejian_runtime.py')
    try:
        if os.name!='nt' and config.stat().st_mode & 0o077:
            raise RuntimeError('连接配置须仅本人可读写，请先执行 chmod 600 connection.json。')
        module = load(active_runtime(config, bundled))
        client = module.Client(config)
        discovery = client.refresh()
        current = client.prepare_runtime()
        if current.resolve() != Path(module.__file__).resolve():
            try:
                candidate = load(current)
                if not callable(getattr(candidate,'Client',None)) or not callable(getattr(candidate,'main',None)):
                    raise RuntimeError()
                replacement = candidate.Client(config)
            except Exception:
                raise RuntimeError('新版客户端无法启动，已保留原版本；尚未写入数据。') from None
            client.activate_runtime(current)
            module,client = candidate,replacement
        return module.main(client=client, pending_updates=discovery.get('updates'))
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        # No request has been written by this launcher. Do not retry a command here.
        print('课间连接失败：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
