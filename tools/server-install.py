#!/usr/bin/env python3
"""Run over SSH stdin. Validate/extract a release without trusting tar paths."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys
import tarfile

root=Path(sys.argv[1]);archive=Path(sys.argv[2]);business,version,health,port,environment=sys.argv[3:]
if not root.is_absolute() or root.is_symlink() or not root.is_dir():raise SystemExit('Project root must already exist as a regular directory.')
releases=root/'releases'
if releases.is_symlink():raise SystemExit('Unsafe release directory.')
releases.mkdir(exist_ok=True)
files={}
with tarfile.open(archive,'r:gz') as tar:
    members=tar.getmembers()
    if len(members)>128 or sum(member.size for member in members)>5_000_000:raise SystemExit('Oversized deployment package.')
    for member in members:
        path=PurePosixPath(member.name)
        if not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in member.name or path.parts[0]!=version or len(path.parts)<2:raise SystemExit('Unsafe deployment package path or type.')
        name='/'.join(path.parts[1:])
        if member.name!=version+'/'+name or name in files:raise SystemExit('Noncanonical or duplicate package path.')
        files[name]=tar.extractfile(member).read()
if not {'SHA256SUMS','release.json','release.env','compose.prod.yaml','scripts/deploy.sh','scripts/lib.py'}<=files.keys():raise SystemExit('Incomplete deployment package.')
sums={}
for line in files['SHA256SUMS'].decode().splitlines():
    match=re.fullmatch(r'([a-f0-9]{64})  (.+)',line)
    if not match or match[2] in sums:raise SystemExit('Invalid package checksums.')
    sums[match[2]]=match[1]
if set(sums)!=set(files)-{'SHA256SUMS'} or any(hashlib.sha256(files[name]).hexdigest()!=digest for name,digest in sums.items()):raise SystemExit('Package checksum mismatch.')
metadata=json.loads(files['release.json'])
if metadata['business']!=business or metadata['version']!=version or metadata['standard_version']!='1.0':raise SystemExit('Package business/version mismatch.')
target=releases/version
if target.exists():
    if target.is_symlink() or {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}!=set(files):raise SystemExit('Existing version differs; overwrite is forbidden.')
    if any((target/name).is_symlink() or (target/name).read_bytes()!=data for name,data in files.items()):raise SystemExit('Existing version content differs; overwrite is forbidden.')
else:
    # Files are small, checked and exclusively created under the selected release.
    target.mkdir(mode=0o755)
    for name,data in files.items():
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o755 if name.endswith('.sh') else 0o644)
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('release_lib',target/'scripts/lib.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
config=module.config(root)
if config['APP_PORT']!=port or config['PUBLIC_HEALTH_URL']!=health or config['ENVIRONMENT']!=environment:raise SystemExit('Workflow inputs differ from the server configuration; no environment file was changed.')
subprocess.run(['bash',str(target/'scripts/deploy.sh'),str(root),str(target)],check=True)
archive.unlink()
