#!/usr/bin/env python3
"""Private data validation and subprocess boundary for the Bash entrypoints."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import tempfile
from urllib.parse import unquote, urlsplit, parse_qsl

SLUG = r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*'
REF = r'ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*@sha256:[0-9a-f]{64}'
CONFIG_KEYS = {'BUSINESS', 'ENVIRONMENT', 'COMPOSE_PROJECT_NAME', 'APP_PORT', 'DATABASE_URL',
               'MIGRATION_DATABASE_URL', 'BACKUP_DATABASE_URL', 'PUBLIC_HEALTH_URL', 'HEALTH_TIMEOUT'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dotenv(path, allowed=None, private=False):
    require(path.is_file() and not path.is_symlink(), 'missing or unsafe environment file')
    if private:
        mode = path.stat()
        require(stat.S_IMODE(mode.st_mode) == 0o600 and mode.st_uid == os.geteuid(),
                'secret environment files must be owned by this user with mode 600')
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        require(sep and re.fullmatch(r'[A-Z][A-Z0-9_]*', key), 'invalid environment assignment')
        require(key not in values and (allowed is None or key in allowed), 'unknown or duplicate environment key')
        if value.startswith(('"', "'")):
            require(len(value) >= 2 and value[-1] == value[0], 'unclosed environment quote')
            value = value[1:-1]
        require('\x00' not in value and '\r' not in value, 'invalid environment value')
        values[key] = value
    return values


def config(root):
    require(root.is_absolute() and root.is_dir(), 'project root must be an existing absolute directory')
    require(not (root / 'shared').is_symlink(), 'shared directory must not be a symlink')
    values = dotenv(root / 'shared/.env.prod', CONFIG_KEYS, private=True)
    require(CONFIG_KEYS - {'BACKUP_DATABASE_URL', 'HEALTH_TIMEOUT'} <= values.keys(), 'missing production configuration')
    require(re.fullmatch(SLUG, values['BUSINESS']) and re.fullmatch(SLUG, values['ENVIRONMENT']), 'invalid business or environment')
    require(values['COMPOSE_PROJECT_NAME'] == values['BUSINESS'] + '-' + values['ENVIRONMENT'], 'unstable Compose project name')
    require(re.fullmatch(r'31[0-9]{3}', values['APP_PORT']), 'APP_PORT must be 31000 through 31999')
    values.setdefault('HEALTH_TIMEOUT', '120')
    require(values['HEALTH_TIMEOUT'].isdigit() and 1 <= int(values['HEALTH_TIMEOUT']) <= 3600, 'invalid health timeout')
    if not values.get('BACKUP_DATABASE_URL'):
        values['BACKUP_DATABASE_URL'] = values['MIGRATION_DATABASE_URL']
    for key in ('DATABASE_URL', 'MIGRATION_DATABASE_URL', 'BACKUP_DATABASE_URL'):
        uri = urlsplit(values[key])
        require(uri.scheme in ('postgres', 'postgresql') and uri.hostname and uri.path.strip('/'), 'invalid PostgreSQL URL')
        require(not uri.fragment, 'invalid PostgreSQL URL fragment')
    health = urlsplit(values['PUBLIC_HEALTH_URL'])
    require(health.scheme in ('http', 'https') and health.hostname and not health.username and not health.password
            and not health.query and not health.fragment, 'public health URL must not contain credentials, query or fragment')
    return values


def release(path, business, root):
    require(path.is_absolute() and path.is_dir() and not path.is_symlink(), 'release must be an absolute regular directory')
    files = {}
    for entry in path.rglob('*'):
        require(not entry.is_symlink(), 'release contains a symlink')
        require(entry.is_file() or entry.is_dir(), 'release contains a special file')
        if entry.is_file():
            relative = entry.relative_to(path).as_posix()
            require(relative in {'release.env', 'release.json', 'compose.prod.yaml', 'SHA256SUMS', 'nginx/site.conf.example'}
                    or re.fullmatch(r'scripts/[a-zA-Z0-9_.-]+\.(sh|py)', relative), 'unexpected file in release bundle')
            files[relative] = entry
    require({'release.env', 'release.json', 'compose.prod.yaml', 'SHA256SUMS', 'nginx/site.conf.example', 'scripts/deploy.sh'} <= files.keys(), 'incomplete release bundle')
    checksums = {}
    for line in files['SHA256SUMS'].read_text().splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  (.+)', line)
        require(match is not None, 'invalid checksum entry')
        digest, name = match.groups()
        parts = PurePosixPath(name)
        require(not parts.is_absolute() and '..' not in parts.parts and '\\' not in name
                and name == parts.as_posix() and name != 'SHA256SUMS' and name not in checksums, 'unsafe checksum path')
        require(name in files, 'checksum names a missing bundle file')
        require(hashlib.sha256(files[name].read_bytes()).hexdigest() == digest, 'bundle checksum mismatch')
        checksums[name] = digest
    require(set(checksums) == set(files) - {'SHA256SUMS'}, 'checksum manifest does not cover every file')
    data = json.loads(files['release.json'].read_text())
    require(data['standard_version'] == '1.0' and data['business'] == business, 'release belongs to another standard or business')
    require(re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', data['version']), 'invalid release version')
    require(re.fullmatch(r'[a-f0-9]{40}', data['commit']), 'invalid release commit')
    require(path == root / 'releases' / data['version'] and not (root / 'releases').is_symlink(), 'release must be PROJECT_ROOT/releases/VERSION')
    require(data['platform'] == 'linux/amd64', 'unsupported release platform')
    base = data['base_path']
    require(base == '' or (re.fullmatch(r'/[A-Za-z0-9_/-]+', base) and not base.endswith('/')
            and '//' not in base and '..' not in base.split('/')), 'invalid base path')
    images = dotenv(files['release.env'], {'APP_IMAGE', 'MIGRATE_IMAGE'})
    require(set(images) == {'APP_IMAGE', 'MIGRATE_IMAGE'}, 'incomplete release image environment')
    for service, key in (('app', 'APP_IMAGE'), ('migrate', 'MIGRATE_IMAGE')):
        image = data['images'][service]
        require(re.fullmatch(REF, images[key]) and images[key] == image['ref'], 'release image reference mismatch')
        require(images[key].split('@')[0].endswith('/' + business + '-' + service), 'image business or role mismatch')
        require(re.fullmatch('sha-' + data['commit'] + (r'(?:-[a-z0-9][a-z0-9-]*)?' if service == 'app' else ''), image['tag']), 'image tag does not match release commit')
    return data, images


def environment(root, path, kind):
    values = config(root)
    data, images = release(path, values['BUSINESS'], root)
    values.update(images, BASE_PATH=data['base_path'])
    values.pop('BACKUP_DATABASE_URL')
    if kind == 'runtime':
        # Compose expands all profiles, including migrate's required variable,
        # even for app-only commands. Use an inert value instead of its secret.
        values['MIGRATION_DATABASE_URL'] = 'postgresql://unused@127.0.0.1/unused'
    else:
        values['DATABASE_URL'] = values['MIGRATION_DATABASE_URL']
    # Compose receives only explicitly selected interpolation values. Parent shell
    # variables cannot override the release digests or the stored configuration.
    env = {key: os.environ[key] for key in ('PATH', 'HOME') if key in os.environ}
    env.update(values)
    return env


def compose(root, path, kind, args, capture=False, bootstrap=False):
    env = environment(root, path, kind)
    extra = []
    if bootstrap and (root / 'shared/.env.bootstrap').exists():
        keys = dotenv(root / 'shared/.env.bootstrap', private=True)
        require(all(key.startswith('BOOTSTRAP_') for key in keys), 'bootstrap environment keys must start with BOOTSTRAP_')
        env.update(keys)
        for key in keys:
            extra.extend(['-e', key])
    if extra:
        index = args.index('migrate')
        args = args[:index] + extra + args[index:]
    command = ['docker', 'compose', '--env-file', '/dev/null', '--project-directory', str(path),
               '-f', str(path / 'compose.prod.yaml'), '-p', env['COMPOSE_PROJECT_NAME'], *args]
    if capture:
        return subprocess.run(command, env=env, capture_output=True, check=False)
    with tempfile.NamedTemporaryFile(mode='wb', prefix='compose-', suffix='.log', dir=root / 'logs', delete=False) as log:
        os.chmod(log.name, 0o600)
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    print('Private operation log: ' + log.name, file=sys.stderr)
    return result


def validate_compose(root, path):
    values = config(root)
    data, images = release(path, values['BUSINESS'], root)
    result = compose(root, path, 'runtime', ['--profile', 'ops', 'config', '--format', 'json'], capture=True)
    require(result.returncode == 0, 'Compose configuration could not be rendered')
    services = json.loads(result.stdout)['services']
    require(set(services) == {'app', 'migrate'}, 'production Compose must contain only app and migrate')
    for name in ('app', 'migrate'):
        service = services[name]
        require(service.get('image') == images[name.upper() + '_IMAGE'], 'Compose uses an unpinned or mismatched image')
        require(not any(service.get(key) for key in ('build', 'volumes', 'env_file', 'secrets', 'configs', 'devices', 'privileged', 'network_mode', 'cap_add')), 'unsafe production service configuration')
        require(not service.get('depends_on'), 'production service has dependencies')
    app, migrate = services['app'], services['migrate']
    ports = app.get('ports', [])
    require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1'
            and str(ports[0].get('published')) == values['APP_PORT'] and ports[0].get('target') == 8080, 'app port must bind to loopback at configured port')
    require(app.get('restart') == 'unless-stopped' and '/app/bin/healthcheck' in app.get('healthcheck', {}).get('test', []), 'app restart or healthcheck is missing')
    require(not app.get('profiles'), 'app must be an ordinary service')
    require(migrate.get('profiles') == ['ops'] and migrate.get('restart') == 'no'
            and not migrate.get('ports'), 'migration must be a one-shot ops service without ports')
    app_env = app.get('environment', {})
    require(app_env.get('DATABASE_URL') == values['DATABASE_URL'], 'app database environment mismatch')
    require(app_env.get('BASE_PATH', '') == data['base_path'], 'app base path does not match release metadata')
    require(not app_env.get('MIGRATION_DATABASE_URL') and not app_env.get('BACKUP_DATABASE_URL'), 'app must not receive administrative database credentials')


def backup(root, filename):
    uri = urlsplit(config(root)['BACKUP_DATABASE_URL'])
    env = {key: os.environ[key] for key in ('PATH', 'HOME') if key in os.environ}
    env.update(PGHOST=uri.hostname, PGPORT=str(uri.port or 5432), PGDATABASE=unquote(uri.path[1:]), PGCONNECT_TIMEOUT='10')
    if uri.username is not None:
        env['PGUSER'] = unquote(uri.username)
    if uri.password is not None:
        env['PGPASSWORD'] = unquote(uri.password)
    options = {'sslmode':'PGSSLMODE', 'sslrootcert':'PGSSLROOTCERT', 'sslcert':'PGSSLCERT', 'sslkey':'PGSSLKEY',
               'channel_binding':'PGCHANNELBINDING', 'connect_timeout':'PGCONNECT_TIMEOUT'}
    for key, value in parse_qsl(uri.query, keep_blank_values=True):
        if key == 'schema':
            continue  # ORM schema selection is not a libpq option; backup covers the database.
        require(key in options, 'unsupported backup PostgreSQL connection option')
        env[options[key]] = value
    result = subprocess.run(['pg_dump', '--format=custom', '--file', filename], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(result.returncode == 0, 'database backup failed')
    result = subprocess.run(['pg_restore', '--list', filename], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(result.returncode == 0, 'database backup archive validation failed')


def health(root):
    values = config(root)
    deadline = time.monotonic() + int(values['HEALTH_TIMEOUT'])
    while True:
        remaining = max(1, deadline - time.monotonic())
        result = subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', str(min(10, remaining)),
                                 '--output', '/dev/null', values['PUBLIC_HEALTH_URL']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        if time.monotonic() + 1 >= deadline:
            raise ValueError('public health check failed')
        time.sleep(1)


def activate(root, target, old):
    for name, path in (('previous', old), ('current', target)):
        if path == '-' or (name == 'previous' and path == target):
            continue
        temporary = root / ('.' + name + '.' + str(os.getpid()))
        temporary.symlink_to(path)
        os.replace(temporary, root / name)


def main():
    action, root_arg, *args = sys.argv[1:]
    root = Path(root_arg)
    if action == 'config':
        values = config(root)
        for key in ('BUSINESS', 'HEALTH_TIMEOUT'):
            sys.stdout.buffer.write(key.encode() + b'\0' + values[key].encode() + b'\0')
    elif action == 'validate':
        release(Path(args[0]), config(root)['BUSINESS'], root)
    elif action == 'compose-check':
        validate_compose(root, Path(args[0]))
    elif action in ('compose', 'bootstrap'):
        result = compose(root, Path(args[0]), args[1], args[2:], bootstrap=action == 'bootstrap')
        sys.exit(result.returncode)
    elif action == 'backup':
        backup(root, args[0])
    elif action == 'health':
        health(root)
    elif action == 'activate':
        activate(root, args[0], args[1])
    elif action == 'images':
        _, images = release(Path(args[0]), config(root)['BUSINESS'], root)
        for ref in images.values():
            print(ref)
    elif action == 'link':
        link = root / args[0]
        if link.is_symlink():
            target = link.resolve(strict=True)
            release(target, config(root)['BUSINESS'], root)
            print(target)
        else:
            require(not link.exists(), 'release link is not a symlink')
    else:
        raise ValueError('unknown helper action')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
        print('Deployment validation or operation failed; check configuration, bundle and service availability.', file=sys.stderr)
        sys.exit(1)
