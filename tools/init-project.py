#!/usr/bin/env python3
import argparse
from pathlib import Path
from standards import init_project
p=argparse.ArgumentParser(description='Generate a project pinned to deployment standard v1.')
p.add_argument('--business',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--standards-ref',required=True);p.add_argument('--owner',default='JojoShine')
a=p.parse_args()
try:init_project(Path(__file__).resolve().parents[1],a.output,a.business,a.standards_ref,a.owner)
except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
print('Generated',a.output)
