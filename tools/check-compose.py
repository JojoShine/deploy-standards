#!/usr/bin/env python3
import argparse
from pathlib import Path
import yaml
from standards import check_compose
p=argparse.ArgumentParser(description='Validate the production Compose contract before publishing.')
p.add_argument('path',type=Path);a=p.parse_args()
try:check_compose(yaml.safe_load(a.path.read_text()))
except (ValueError,OSError,yaml.YAMLError) as e:p.exit(1,str(e)+'\n')
print('Production Compose contract passed.')
