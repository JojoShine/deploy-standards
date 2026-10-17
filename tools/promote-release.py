#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from registry import promote
from standards import validate_version,validate_business,validate_image_ref
p=argparse.ArgumentParser();p.add_argument('--candidate',required=True,type=Path);p.add_argument('--version',required=True);p.add_argument('--project-dir',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();validate_version(a.version)
data=json.loads(a.candidate.read_text());validate_business(data['business'])
# Validate every formal tag before changing any of them; retries can finish a partial promotion.
from registry import descriptor
for service in ['app','migrate']:
    item=data['images'][service];validate_image_ref(item['ref'],data['business'],service)
    suffix='-'+data['variant'] if service=='app' and data.get('variant') else ''
    tag=item['ref'].split('@')[0]+':'+a.version+suffix
    current=descriptor(tag)
    if current and current['digest']!=item['ref'].split('@')[1]:raise SystemExit('Formal version already points to another image; choose a new version.')
for service in ['app','migrate']:
    suffix='-'+data['variant'] if service=='app' and data.get('variant') else ''
    item=data['images'][service];promote(item['ref'],item['ref'].split('@')[0]+':'+a.version+suffix)
from standards import pack_release
pack_release(a.project_dir,a.output,data['business'],a.version,data['commit'],data['images']['app']['ref'],data['images']['migrate']['ref'],data['base_path'],data.get('variant',''),data['platform'])
print('Promoted existing image digests and packaged matching configuration; no rebuild.')
