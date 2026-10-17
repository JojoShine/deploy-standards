#!/usr/bin/env python3
"""Fetch metadata only from a successful main push CI run for the tagged commit."""
import argparse,io,json,subprocess,zipfile
from pathlib import Path
from standards import validate_business,validate_sha,validate_image_ref
p=argparse.ArgumentParser();p.add_argument('--business',required=True);p.add_argument('--commit',required=True);p.add_argument('--repository',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--base-path',default='');p.add_argument('--variant',default='');a=p.parse_args();validate_business(a.business);validate_sha(a.commit)
def api(path):return json.loads(subprocess.check_output(['gh','api',path],text=True))
runs=api(f'repos/{a.repository}/actions/workflows/ci.yml/runs?head_sha={a.commit}&event=push&per_page=100')['workflow_runs']
for run in runs:
    if run['head_branch']!='main' or run['conclusion']!='success':continue
    artifacts=api(f'repos/{a.repository}/actions/runs/{run["id"]}/artifacts?per_page=100')['artifacts']
    artifact=next((item for item in artifacts if item['name']=='candidate-'+a.commit and not item['expired']),None)
    if not artifact:continue
    raw=subprocess.check_output(['gh','api',f'repos/{a.repository}/actions/artifacts/{artifact["id"]}/zip'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.namelist()!=['candidate.json']:raise ValueError('unexpected candidate artifact contents')
        data=json.loads(archive.read('candidate.json'))
    for key,value in [('business',a.business),('commit',a.commit),('repository',a.repository),('standard_version','1.0'),('platform','linux/amd64'),('base_path',a.base_path),('variant',a.variant)]:
        if data.get(key)!=value:raise ValueError('candidate provenance/configuration mismatch: '+key)
    for service in ['app','migrate']:
        validate_image_ref(data['images'][service]['ref'],a.business,service)
        if data['images'][service]['ref'].split('/')[1]!=a.repository.split('/')[0].lower():raise ValueError('candidate owner mismatch')
    a.output.write_text(json.dumps(data,indent=2)+'\n');print('Verified successful main CI candidate.');break
else:raise SystemExit('No successful main CI candidate exists for this commit. Finish CI before creating the version tag.')
