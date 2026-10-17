#!/usr/bin/env python3
import argparse,json,re
from pathlib import Path
from registry import push_immutable
from standards import validate_business,validate_sha,validate_base_path
p=argparse.ArgumentParser();p.add_argument('--business',required=True);p.add_argument('--commit',required=True);p.add_argument('--repository',required=True);p.add_argument('--app-local',required=True);p.add_argument('--migrate-local',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--base-path',default='');p.add_argument('--variant',default='');a=p.parse_args()
validate_business(a.business);validate_sha(a.commit);validate_base_path(a.base_path)
if a.variant:validate_business(a.variant)
if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',a.repository):p.error('invalid repository')
owner=a.repository.split('/')[0].lower();record={'standard_version':'1.0','business':a.business,'commit':a.commit,'repository':a.repository,'platform':'linux/amd64','base_path':a.base_path,'variant':a.variant,'images':{}}
for service,local in [('app',a.app_local),('migrate',a.migrate_local)]:
    suffix='-'+a.variant if service=='app' and a.variant else ''
    tag=f'ghcr.io/{owner}/{a.business}-{service}:sha-{a.commit}{suffix}'
    record['images'][service]={'ref':push_immutable(local,tag),'tag':tag}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(record,indent=2)+'\n')
print('Immutable candidate images published and recorded.')
