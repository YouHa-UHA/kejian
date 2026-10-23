"""Small, authenticated client release; credentials are never part of an update."""
import hashlib
import json
from pathlib import Path

BOOTSTRAP_PROTOCOL = 1
CLIENT_VERSION = '2.0.0'
API_VERSION = 'kejian-agent-v1'


def release(include_source=False):
    source = Path(__file__).with_name('agent_client.py').read_text(encoding='utf-8')
    data = source.encode('utf-8')
    manifest = {'apiVersion': API_VERSION, 'bootstrapProtocol': BOOTSTRAP_PROTOCOL,
                'clientVersion': CLIENT_VERSION,
                'files': [{'path': 'kejian_runtime.py', 'sha256': hashlib.sha256(data).hexdigest(),
                           'size': len(data)}]}
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    result = {**manifest, 'revision': hashlib.sha256(raw.encode()).hexdigest(), 'path': '/client-release'}
    if include_source:
        result['sources'] = {'kejian_runtime.py': source}
    return result
