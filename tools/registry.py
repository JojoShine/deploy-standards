"""GHCR image operations preserving immutable tags and byte-identical manifests."""
import json
import subprocess


def run(*args):
    return subprocess.check_output(list(args), text=True).strip()


def descriptor(ref):
    result = subprocess.run(['docker','buildx','imagetools','inspect',ref,'--format','{{json .Manifest}}'],text=True,capture_output=True)
    if result.returncode:
        message=result.stderr.lower()
        if any(marker in message for marker in ['not found','manifest unknown','404','name_unknown']):return None
        raise RuntimeError('registry inspection failed; no tag was changed')
    return json.loads(result.stdout)


def push_immutable(local, tag):
    config=run('docker','image','inspect',local,'--format','{{.Id}}')
    existing=descriptor(tag)
    if existing:
        raw=json.loads(run('docker','buildx','imagetools','inspect',tag,'--raw'))
        if raw.get('config',{}).get('digest')!=config:
            raise ValueError('immutable SHA tag already points to different image content')
        return tag.split(':')[0]+'@'+existing['digest']
    subprocess.run(['docker','tag',local,tag],check=True)
    subprocess.run(['docker','push',tag],check=True)
    published=descriptor(tag)
    if not published:raise RuntimeError('published image was not readable')
    return tag.split(':')[0]+'@'+published['digest']


def promote(ref, tag):
    expected=ref.split('@',1)[1];existing=descriptor(tag)
    if existing and existing['digest']!=expected:
        raise ValueError('formal version tag already exists with a different digest')
    if not existing:
        subprocess.run(['docker','buildx','imagetools','create','--prefer-index=false','--tag',tag,ref],check=True)
    actual=descriptor(tag)
    if not actual or actual['digest']!=expected:
        raise RuntimeError('version promotion did not preserve the tested manifest digest')
