#!/usr/bin/env python3
import argparse
from standards import check_callers
p=argparse.ArgumentParser();p.add_argument('--project-dir',required=True);p.add_argument('--standards-ref',required=True);p.add_argument('--business',required=True);a=p.parse_args()
try:check_callers(a.project_dir,a.standards_ref,a.business)
except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
print('All three caller workflows use the same pinned standard and business.')
