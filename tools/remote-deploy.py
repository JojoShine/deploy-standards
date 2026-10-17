#!/usr/bin/env python3
"""Transport only a versioned deployment package; server secrets stay on the server."""
import argparse,os,re,shlex,subprocess,tempfile,uuid
from pathlib import Path
from standards import validate_business,validate_version
p=argparse.ArgumentParser();p.add_argument('--bundle',required=True,type=Path);a=p.parse_args()
e=os.environ;business=validate_business(e['BUSINESS']);version=validate_version(e['VERSION']);environment=validate_business(e['DEPLOY_ENV'])
host,user,port=e['SSH_HOST'],e['SSH_USER'],e.get('SSH_PORT','22')
if not re.fullmatch(r'[a-zA-Z0-9.-]+',host) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*',user):raise SystemExit('Invalid SSH destination.')
if not port.isdigit() or not 1<=int(port)<=65535:raise SystemExit('Invalid SSH port.')
if not e['APP_PORT'].isdigit() or not 31000<=int(e['APP_PORT'])<=31999:raise SystemExit('Invalid allocated application port.')
root='/opt/'+business;remote=root+'/.incoming-'+version+'-'+uuid.uuid4().hex+'.tar.gz'
with tempfile.TemporaryDirectory() as tmp:
    key=Path(tmp)/'key';known=Path(tmp)/'known_hosts';key.write_text(e['SSH_PRIVATE_KEY'].rstrip()+'\n');known.write_text(e['SSH_KNOWN_HOSTS'].rstrip()+'\n');key.chmod(0o600);known.chmod(0o600)
    options=['-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known)]
    destination=user+'@'+host
    subprocess.run(['scp',*options,'-P',port,str(a.bundle),destination+':'+remote],check=True)
    command=shlex.join(['python3','-',root,remote,business,version,e['PUBLIC_HEALTH_URL'],e['APP_PORT'],environment])
    script=(Path(__file__).parent/'server-install.py').read_bytes()
    subprocess.run(['ssh',*options,'-p',port,destination,command],input=script,check=True)
