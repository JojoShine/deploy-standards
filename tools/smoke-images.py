#!/usr/bin/env python3
"""Exercise built images and migrations against a disposable PostgreSQL container."""
import argparse,json,subprocess,time,uuid
p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--migrate',required=True);p.add_argument('--postgres-image',default='postgres:16-alpine');p.add_argument('--base-path',default='');a=p.parse_args()
name='standard-smoke-'+uuid.uuid4().hex[:12];db=name+'-db';app=name+'-app';url='postgresql://standard:ci_only_password@db:5432/image_checks'
def call(*args,quiet=False,check=True):return subprocess.run(['docker',*args],check=check,stdout=subprocess.DEVNULL if quiet else None)
try:
    call('network','create',name,quiet=True)
    call('run','-d','--name',db,'--network',name,'--network-alias','db','-e','POSTGRES_DB=image_checks','-e','POSTGRES_USER=standard','-e','POSTGRES_PASSWORD=ci_only_password',a.postgres_image,quiet=True)
    for attempt in range(90):
        if call('exec',db,'pg_isready','-U','standard','-d','image_checks',quiet=True,check=False).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('test PostgreSQL did not become ready')
    for command in ['/app/bin/migrate','/app/bin/migrate','/app/bin/bootstrap','/app/bin/bootstrap']:
        call('run','--rm','--network',name,'-e','DATABASE_URL='+url,a.migrate,command)
    call('run','-d','--name',app,'--network',name,'-e','DATABASE_URL='+url,'-e','BASE_PATH='+a.base_path,'-e','PORT=8080',a.app,quiet=True)
    for attempt in range(90):
        if call('exec',app,'/app/bin/healthcheck',quiet=True,check=False).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('runtime image health check failed')
    data=json.loads(subprocess.check_output(['docker','inspect',app],text=True))[0]
    if data['Config']['User'].split(':',1)[0] in ['','root','0']:raise ValueError('runtime image must use a non-root user')
    if not data['Config'].get('Healthcheck'):raise ValueError('runtime image must define HEALTHCHECK')
    print('Image smoke passed: repeat migrations/bootstrap, health, non-root user.')
finally:
    for container in [app,db]:call('rm','-f',container,quiet=True,check=False)
    call('network','rm',name,quiet=True,check=False)
