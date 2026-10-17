#!/usr/bin/env python3
import argparse
from pathlib import Path
from standards import pack_release
p=argparse.ArgumentParser(description='Package matching deployment config and immutable image references; excludes source and secrets.')
p.add_argument('--project-dir',required=True,type=Path);p.add_argument('--business',required=True);p.add_argument('--version',required=True);p.add_argument('--commit',required=True);p.add_argument('--app-image',required=True);p.add_argument('--migrate-image',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--base-path',default='');p.add_argument('--variant',default='');p.add_argument('--platform',default='linux/amd64')
a=p.parse_args()
try:pack_release(a.project_dir,a.output,a.business,a.version,a.commit,a.app_image,a.migrate_image,a.base_path,a.variant,a.platform)
except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
print(a.output)
