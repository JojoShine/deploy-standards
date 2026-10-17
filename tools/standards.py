"""Versioned project scaffolding and immutable deployment bundle tooling."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile

SLUG = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')
VERSION = re.compile(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}\Z')


def validate_business(value):
    if not isinstance(value, str) or len(value) > 63 or not SLUG.fullmatch(value):
        raise ValueError('business must be a lowercase hyphenated slug, at most 63 characters')
    return value


def validate_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('a full lowercase Git commit SHA is required')
    return value


def validate_version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError('version must be vMAJOR.MINOR.PATCH without leading zeros')
    return value


def validate_base_path(value):
    if value and not re.fullmatch(r'(?:/[a-zA-Z0-9_-]+)+', value):
        raise ValueError('base-path must be empty or a path without trailing slash')
    return value


def validate_image_ref(value, business, service):
    pattern = r'ghcr\.io/[a-z0-9][a-z0-9_-]*/' + re.escape(business + '-' + service) + r'@sha256:[a-f0-9]{64}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'{service} image must be a matching ghcr.io digest reference')
    return value


def check_compose(document):
    services = document.get('services', {})
    if not all(name in services for name in ['app', 'migrate']):
        raise ValueError('production requires app and migrate services')
    for name, service in services.items():
        if 'build' in service or service.get('privileged') or service.get('network_mode') == 'host' or 'container_name' in service:
            raise ValueError(f'{name}: forbidden production build/privilege/host networking/container_name')
        for mount in service.get('volumes', []):
            # Persistent named volumes are allowed; host paths and source bind mounts are not.
            if isinstance(mount, str):
                source = mount.split(':', 1)[0]
                if ':' not in mount or '/' in source or source.startswith('.'):
                    raise ValueError(f'{name}: production bind mount is forbidden')
            elif mount.get('type') != 'volume':
                raise ValueError(f'{name}: production bind mount is forbidden')
        if not service.get('image'):
            raise ValueError(f'{name}: image is required')
        env = service.get('environment', {})
        if not isinstance(env, dict):raise ValueError('environment must use mapping form')
        if name == 'app' and any(key.startswith(('ADMIN_', 'BOOTSTRAP_')) or key == 'MIGRATION_DATABASE_URL' for key in env):
            raise ValueError('runtime must not receive initialization/migration credentials')
        if name not in ['app'] and service.get('ports'):
            raise ValueError(f'{name}: only the web entry may publish host ports')
    app, migrate = services['app'], services['migrate']
    ports = app.get('ports', [])
    if len(ports) != 1 or not isinstance(ports[0], str) or not re.fullmatch(r'127\.0\.0\.1:\$\{APP_PORT(?::\?[^}]*)?\}:8080', ports[0]):
        raise ValueError('app must publish exactly 127.0.0.1:${APP_PORT}:8080')
    if app.get('restart') != 'unless-stopped' or not app.get('healthcheck', {}).get('test'):
        raise ValueError('app requires healthcheck and restart unless-stopped')
    if migrate.get('restart') != 'no' or 'ops' not in migrate.get('profiles', []):
        raise ValueError('migrate must be a one-shot ops profile')
    if app.get('depends_on'):
        raise ValueError('deploy script, not app startup dependencies, controls migration order')


def init_project(root, output, business, ref, owner):
    validate_business(business);validate_sha(ref)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', owner):raise ValueError('invalid GitHub owner')
    root, output = Path(root).resolve(), Path(output).absolute()
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise ValueError('output must be a new or empty non-symlink directory')
    source = root / 'templates/project'
    replacements = {'__BUSINESS__': business, '__OWNER__': owner.lower(), '__STANDARDS_REF__': ref}
    output.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob('*')):
        if any(part in ['node_modules', '__pycache__'] for part in path.relative_to(source).parts):continue
        if path.is_symlink():raise ValueError('template symlinks are not supported')
        target = output / path.relative_to(source)
        if path.is_dir():target.mkdir(parents=True, exist_ok=True);continue
        content = path.read_text()
        for token, value in replacements.items():content = content.replace(token, value)
        target.write_text(content);target.chmod(path.stat().st_mode & 0o777)
    scripts = output / 'scripts';scripts.mkdir(exist_ok=True)
    for path in sorted((root / 'scripts').iterdir()):
        if path.is_file() and path.suffix in ['.sh', '.py']:
            shutil.copy2(path, scripts / path.name)
    (output / '.deployment-standard').write_text('1.0\n' + ref + '\n')


def pack_release(project, output, business, version, commit, app_image, migrate_image, base_path='', variant='', platform='linux/amd64'):
    validate_business(business);validate_version(version);validate_sha(commit);validate_base_path(base_path)
    validate_image_ref(app_image, business, 'app');validate_image_ref(migrate_image, business, 'migrate')
    if app_image.split('/')[1] != migrate_image.split('/')[1]:raise ValueError('images must share the same registry owner')
    if variant:validate_business(variant)
    if platform != 'linux/amd64':raise ValueError('standard v1 currently supports linux/amd64')
    project, output = Path(project), Path(output)
    compose = project / 'compose.prod.yaml'
    if compose.is_symlink() or not compose.is_file():raise ValueError('compose.prod.yaml must be a regular file')
    files = {'compose.prod.yaml': (compose.read_bytes(), 0o644)}
    for folder in ['scripts', 'nginx']:
        directory = project / folder
        if directory.is_symlink():raise ValueError('bundle directories cannot be symlinks')
        for path in sorted(directory.rglob('*')):
            if '__pycache__' in path.parts:continue
            if path.is_symlink():raise ValueError('bundle files cannot be symlinks')
            if path.is_file():
                if folder == 'scripts' and path.suffix not in ['.sh', '.py']:continue
                if folder == 'nginx' and not path.name.endswith('.conf.example'):continue
                files[path.relative_to(project).as_posix()] = (path.read_bytes(), 0o755 if path.suffix == '.sh' else 0o644)
    required={'scripts/deploy.sh','scripts/bootstrap.sh','scripts/rollback.sh','scripts/lib.sh','scripts/lib.py','nginx/site.conf.example'}
    if not required <= files.keys():raise ValueError('project must contain generated scripts and Nginx example')
    metadata = {'standard_version': '1.0', 'business': business, 'version': version, 'commit': commit, 'platform': platform, 'base_path': base_path, 'images': {}}
    for name, ref in [('app', app_image), ('migrate', migrate_image)]:
        suffix = '-' + variant if name == 'app' and variant else ''
        metadata['images'][name] = {'ref': ref, 'tag': 'sha-' + commit + suffix}
    files['release.json'] = ((json.dumps(metadata, indent=2, ensure_ascii=False)+'\n').encode(), 0o644)
    files['release.env'] = (f'APP_IMAGE={app_image}\nMIGRATE_IMAGE={migrate_image}\n'.encode(), 0o644)
    sums = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, (data, _) in sorted(files.items()))
    files['SHA256SUMS'] = (sums.encode(), 0o644)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as zipped, tarfile.open(mode='w', fileobj=zipped) as archive:
        for name, (data, mode) in sorted(files.items()):
            member = tarfile.TarInfo(version + '/' + name);member.size=len(data);member.mode=mode;member.mtime=0
            archive.addfile(member, io.BytesIO(data))
    return metadata


def check_callers(project, ref, business):
    import yaml
    validate_sha(ref);validate_business(business)
    for role in ['ci','release','deploy']:
        path=Path(project)/'.github/workflows'/(role+'.yml')
        document=yaml.safe_load(path.read_text())
        calls=[job for job in document.get('jobs',{}).values() if str(job.get('uses','')).startswith('JojoShine/deploy-standards/.github/workflows/')]
        expected='JojoShine/deploy-standards/.github/workflows/'+role+'.yml@'+ref
        if len(calls)!=1 or calls[0].get('uses')!=expected or calls[0].get('with',{}).get('standard-ref')!=ref or calls[0].get('with',{}).get('business')!=business:
            raise ValueError('caller workflow pin/business mismatch: '+role)
