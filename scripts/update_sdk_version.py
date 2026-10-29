#!/usr/bin/env python3
"""Update the SDK used by Docker and CI: scripts/update_sdk_version.py 4.43."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def update_version(version, root=ROOT):
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid SDK version")
    env = root / '.env'
    text = env.read_text()
    match = re.search(r'^PEBBLE_SDK_VERSION=(.+)$', text, re.M)
    if not match:
        raise ValueError("Missing PEBBLE_SDK_VERSION in .env")
    old = match.group(1)
    workflow = root / '.github/workflows/build-cluster-images.yml'
    workflow_text = workflow.read_text()
    # Read and validate every input before writing. Projects use the image SDK;
    # there is no longer a per-project sdk_version database field.
    env.write_text(text[:match.start(1)] + version + text[match.end(1):])
    workflow.write_text(workflow_text.replace(old, version))
    return old

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: scripts/update_sdk_version.py <sdk-version>')
    try:
        old = update_version(sys.argv[1])
    except ValueError as error:
        sys.exit(str(error))
    print('SDK: %s -> %s' % (old, sys.argv[1]))
