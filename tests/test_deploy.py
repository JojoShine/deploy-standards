import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40
APP = 'ghcr.io/example/shop-app@sha256:' + '1' * 64
MIGRATE = 'ghcr.io/example/shop-migrate@sha256:' + '2' * 64

FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
root = pathlib.Path(__file__).resolve().parent
settings = json.loads((root / 'settings.json').read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
record = {'tool': name, 'args': args}
project = pathlib.Path(settings['project'])
record['current'] = str((project / 'current').resolve()) if (project / 'current').exists() else None
if name == 'docker':
    record['database'] = 'migration' if 'migration-secret' in os.getenv('DATABASE_URL', '') else 'runtime' if 'runtime-secret' in os.getenv('DATABASE_URL', '') else 'none'
    record['bootstrap'] = os.getenv('BOOTSTRAP_ADMIN_PASSWORD') == 'bootstrap-secret'
with (root / 'events.jsonl').open('a') as f: f.write(json.dumps(record) + '\n')
if name == 'docker':
    if '-f' in args and not os.environ.get('MIGRATION_DATABASE_URL'): sys.exit(30)
    if args[:2] == ['image', 'inspect']:
        print(settings.get('platform', 'linux/amd64'))
    elif 'config' in args:
        print(json.dumps({'services': {
          'app': {'image': os.environ['APP_IMAGE'], 'restart':'unless-stopped', 'environment': {'DATABASE_URL':os.environ['DATABASE_URL'], 'BASE_PATH':settings.get('bad_base',os.environ['BASE_PATH'])}, 'ports':[{'host_ip':settings.get('host_ip','127.0.0.1'),'published':os.environ['APP_PORT'],'target':8080}], 'healthcheck': {'test':['CMD','/app/bin/healthcheck']}},
          'migrate': {'image':os.environ['MIGRATE_IMAGE'], 'profiles':['ops'], 'restart':settings.get('migration_restart','no'), 'environment': {'DATABASE_URL':os.environ['MIGRATION_DATABASE_URL']}}
        }}))
    elif 'run' in args and '/app/bin/migrate' in args:
        if settings.get('migration_delay'): time.sleep(settings['migration_delay'])
        if settings.get('migration_fail'): sys.exit(21)
    elif 'up' in args and settings.get('up_fail') and any('v2.0.0' in a for a in args): sys.exit(22)
elif name == 'pg_dump':
    pathlib.Path(args[args.index('--file') + 1]).write_bytes(b'PGDMP fixture')
    if settings.get('backup_fail'): sys.exit(25)
elif name == 'pg_restore' and settings.get('archive_fail'): sys.exit(26)
elif name == 'curl' and settings.get('health_fail'):
    count = settings.get('curl_count', 0)
    settings['curl_count'] = count + 1
    (root / 'settings.json').write_text(json.dumps(settings))
    if count == 0: sys.exit(23)
'''


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'shop'
        (self.root / 'shared').mkdir(parents=True)
        (self.root / 'releases').mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name in ('docker', 'pg_dump', 'pg_restore', 'curl'):
            path = self.bin / name
            path.write_text(FAKE)
            path.chmod(0o755)
        (self.bin / 'flock').write_text('#!/usr/bin/env python3\nimport fcntl, sys\nfcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX)\n')
        (self.bin / 'flock').chmod(0o755)
        (self.bin / 'settings.json').write_text(json.dumps({'project':str(self.root)}))
        self.secret = self.root / 'shared/.env.prod'
        self.secret.write_text('BUSINESS=shop\nENVIRONMENT=production\nCOMPOSE_PROJECT_NAME=shop-production\nAPP_PORT=31001\nDATABASE_URL=postgresql://app:runtime-secret@db/app\nMIGRATION_DATABASE_URL=postgresql://owner:migration-secret@db/app\nPUBLIC_HEALTH_URL=https://shop.example/healthz\nHEALTH_TIMEOUT=1\n')
        self.secret.chmod(0o600)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'])
        self.old = self.release('v1.0.0')
        self.new = self.release('v2.0.0')

    def release(self, version):
        path = self.root / 'releases' / version
        (path / 'scripts').mkdir(parents=True)
        (path / 'nginx').mkdir()
        (path / 'compose.prod.yaml').write_text('services: {}\n')
        (path / 'release.env').write_text(f'APP_IMAGE={APP}\nMIGRATE_IMAGE={MIGRATE}\n')
        data = {'standard_version':'1.0','business':'shop','version':version,'commit':COMMIT,'platform':'linux/amd64','base_path':'','images':{'app':{'ref':APP,'tag':'sha-'+COMMIT},'migrate':{'ref':MIGRATE,'tag':'sha-'+COMMIT}}}
        (path / 'release.json').write_text(json.dumps(data))
        (path / 'nginx/site.conf.example').write_text('# example\n')
        (path / 'scripts/deploy.sh').write_text('#!/bin/bash\n')
        self.checksums(path)
        return path

    def checksums(self, path):
        files = sorted(p for p in path.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
        (path / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(path)) + '\n' for p in files))

    def settings(self, **kwargs):
        (self.bin / 'settings.json').write_text(json.dumps({'project':str(self.root), **kwargs}))

    def events(self):
        path = self.bin / 'events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(REPO / 'scripts' / name), str(self.root), *map(str,args)], env=self.env, capture_output=True, text=True)

    def linked_old(self):
        (self.root / 'current').symlink_to(self.old)

    def assert_no_secrets(self, result):
        output = result.stdout + result.stderr + json.dumps(self.events())
        for secret in ('runtime-secret', 'migration-secret', 'bootstrap-secret'):
            self.assertNotIn(secret, output)

    def test_fresh_deploy_orders_backup_migration_health_and_activation(self):
        result = self.run_script('deploy.sh', self.new)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.events()
        dump = next(i for i,e in enumerate(events) if e['tool']=='pg_dump')
        restore = next(i for i,e in enumerate(events) if e['tool']=='pg_restore')
        migrate = next(i for i,e in enumerate(events) if '/app/bin/migrate' in e['args'])
        up = next(i for i,e in enumerate(events) if 'up' in e['args'])
        health = next(i for i,e in enumerate(events) if e['tool']=='curl')
        self.assertLess(dump, restore)
        self.assertLess(restore, migrate)
        self.assertLess(migrate, up)
        self.assertLess(up, health)
        self.assertIsNone(events[health]['current'])
        self.assertEqual((self.root/'current').resolve(), self.new)
        self.assertFalse((self.root/'previous').exists())
        self.assertEqual(events[migrate]['database'], 'migration')
        self.assertEqual(events[up]['database'], 'runtime')
        self.assert_no_secrets(result)

    def test_upgrade_sets_previous_only_after_success(self):
        self.linked_old()
        result = self.run_script('deploy.sh', self.new)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root/'current').resolve(), self.new)
        self.assertEqual((self.root/'previous').resolve(), self.old)
        self.assertTrue(all(e['current'] == str(self.old) for e in self.events()))

    def test_failed_migration_preserves_current_without_starting_app(self):
        self.linked_old()
        self.settings(migration_fail=True)
        result = self.run_script('deploy.sh', self.new)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root/'current').resolve(), self.old)
        self.assertFalse(any('up' in e['args'] for e in self.events()))
        self.assert_no_secrets(result)

    def test_failed_upgrade_health_restores_previous_app_without_migration(self):
        self.linked_old()
        self.settings(health_fail=True)
        result = self.run_script('deploy.sh', self.new)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root/'current').resolve(), self.old)
        ups = [e for e in self.events() if 'up' in e['args']]
        self.assertEqual(len(ups), 2)
        self.assertIn(str(self.old/'compose.prod.yaml'), ups[-1]['args'])
        self.assertEqual(sum('/app/bin/migrate' in e['args'] for e in self.events()),1)
        self.assertFalse(any('--clean' in e['args'] for e in self.events()))

    def test_first_deploy_failure_leaves_no_current_and_stops_candidate(self):
        self.settings(health_fail=True)
        result = self.run_script('deploy.sh', self.new)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'current').exists())
        self.assertTrue(any('stop' in e['args'] and 'app' in e['args'] for e in self.events()))

    def test_manual_rollback_swaps_links_without_database_operations(self):
        self.linked_old()
        (self.root/'previous').symlink_to(self.new)
        result = self.run_script('rollback.sh')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root/'current').resolve(),self.new)
        self.assertEqual((self.root/'previous').resolve(),self.old)
        self.assertFalse(any(e['tool'].startswith('pg_') or '/app/bin/migrate' in e['args'] for e in self.events()))

    def test_bootstrap_passes_private_environment_without_reset(self):
        self.linked_old()
        bootstrap = self.root/'shared/.env.bootstrap'
        bootstrap.write_text('BOOTSTRAP_ADMIN_PASSWORD=bootstrap-secret\n')
        bootstrap.chmod(0o600)
        for _ in range(2):
            result = self.run_script('bootstrap.sh')
            self.assertEqual(result.returncode,0,result.stderr)
        calls=[e for e in self.events() if '/app/bin/bootstrap' in e['args']]
        self.assertEqual(len(calls),2)
        self.assertTrue(all(e['bootstrap'] for e in calls))
        self.assertTrue(all(e['database']=='migration' for e in calls))
        self.assert_no_secrets(result)

    def test_malicious_env_is_data_never_executed(self):
        marker=self.base/'injected'
        with self.secret.open('a') as f:f.write(f'EVIL=$(touch {marker})\n')
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.events(),[])

    def test_shell_substitution_inside_quoted_password_is_literal(self):
        marker=self.base/'injected'
        self.secret.write_text(self.secret.read_text().replace('runtime-secret',f'$(touch%20{marker})'))
        result=self.run_script('deploy.sh',self.new)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(marker.exists())

    def test_rejects_checksum_tampering_and_traversal(self):
        for bad in ('tamper','traversal'):
            with self.subTest(bad=bad):
                self.checksums(self.new)
                if bad=='tamper':(self.new/'compose.prod.yaml').write_text('tampered')
                else:
                    with (self.new/'SHA256SUMS').open('a') as f:f.write('0'*64+'  ../outside\n')
                result=self.run_script('deploy.sh',self.new)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(self.events(),[])

    def test_rejects_unsafe_project_env_and_image_platform(self):
        self.secret.write_text(self.secret.read_text().replace('APP_PORT=31001','APP_PORT=80'))
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.events(),[])

    def test_invalid_archive_prevents_migration(self):
        self.settings(archive_fail=True)
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('/app/bin/migrate' in e['args'] for e in self.events()))

    def test_wrong_image_architecture_prevents_backup_and_migration(self):
        self.settings(platform='linux/arm64')
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(e['tool'].startswith('pg_') for e in self.events()))
        self.assertFalse(any('/app/bin/migrate' in e['args'] for e in self.events()))

    def test_failed_backup_prevents_migration_and_removes_partial_archive(self):
        self.settings(backup_fail=True)
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(list((self.root/'backups').iterdir()),[])
        self.assertFalse(any('/app/bin/migrate' in e['args'] for e in self.events()))

    def test_failed_app_start_recovers_old_app(self):
        self.linked_old()
        self.settings(up_fail=True)
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        ups=[e for e in self.events() if 'up' in e['args']]
        self.assertEqual(len(ups),2)
        self.assertIn(str(self.old/'compose.prod.yaml'),ups[-1]['args'])
        self.assertEqual((self.root/'current').resolve(),self.old)

    def test_rejects_symlinked_or_uncovered_bundle_files_before_docker(self):
        for bad in ('symlink','uncovered'):
            with self.subTest(bad=bad):
                extra=self.new/'scripts/extra.sh'
                if bad=='symlink':extra.symlink_to(self.secret)
                else:extra.write_text('not covered')
                result=self.run_script('deploy.sh',self.new)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(self.events(),[])
                extra.unlink()

    def test_rejects_world_readable_secrets(self):
        self.secret.chmod(0o644)
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.events(),[])

    def test_parent_environment_cannot_override_release_images_or_databases(self):
        self.env.update(APP_IMAGE='ghcr.io/evil/image:latest', DATABASE_URL='postgresql://evil:wrong@db/app', BASE_PATH='/wrong')
        result=self.run_script('deploy.sh',self.new)
        self.assertEqual(result.returncode,0,result.stderr)
        migration=next(e for e in self.events() if '/app/bin/migrate' in e['args'])
        self.assertEqual(migration['database'],'migration')
        self.assertFalse(any('ghcr.io/evil' in ' '.join(e['args']) for e in self.events()))

    def test_concurrent_deploys_are_serialized(self):
        import time
        self.settings(migration_delay=0.6)
        first=subprocess.Popen(['bash',str(REPO/'scripts/deploy.sh'),str(self.root),str(self.old)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and not any('/app/bin/migrate' in e['args'] for e in self.events()):
            time.sleep(0.02)
        second=subprocess.Popen(['bash',str(REPO/'scripts/deploy.sh'),str(self.root),str(self.new)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        first_out=first.communicate(timeout=20)
        second_out=second.communicate(timeout=20)
        self.assertEqual(first.returncode,0,first_out)
        self.assertEqual(second.returncode,0,second_out)
        events=self.events()
        migrations=[i for i,e in enumerate(events) if '/app/bin/migrate' in e['args']]
        healths=[i for i,e in enumerate(events) if e['tool']=='curl']
        self.assertEqual(len(migrations),2)
        self.assertLess(healths[0],migrations[1])
        self.assertEqual((self.root/'current').resolve(),self.new)
        self.assertEqual((self.root/'previous').resolve(),self.old)

    def test_compose_base_path_must_match_release_metadata(self):
        self.settings(bad_base='/wrong')
        result=self.run_script('deploy.sh',self.new)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('/app/bin/migrate' in e['args'] for e in self.events()))

    def test_redeploy_keeps_existing_previous_release(self):
        (self.root/'current').symlink_to(self.new)
        (self.root/'previous').symlink_to(self.old)
        result=self.run_script('deploy.sh',self.new)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root/'previous').resolve(),self.old)

    def test_blank_backup_url_uses_migration_connection(self):
        with self.secret.open('a') as f:f.write('BACKUP_DATABASE_URL=\n')
        result=self.run_script('deploy.sh',self.new)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_bootstrap_rejects_non_bootstrap_environment(self):
        self.linked_old()
        bootstrap=self.root/'shared/.env.bootstrap'
        bootstrap.write_text('PATH=/malicious\n')
        bootstrap.chmod(0o600)
        result=self.run_script('bootstrap.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('/app/bin/bootstrap' in e['args'] for e in self.events()))

    def test_release_must_be_under_project_releases_with_matching_version(self):
        external=self.base/'external'
        self.new.rename(external)
        result=self.run_script('deploy.sh',external)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.events(),[])

    def test_real_template_compose_renders_without_admin_credentials_for_app(self):
        import shutil
        docker=shutil.which('docker')
        if not docker or subprocess.run([docker,'compose','version'],capture_output=True).returncode:
            self.skipTest('Docker Compose CLI is unavailable')
        (self.new/'compose.prod.yaml').write_text((REPO/'templates/project/compose.prod.yaml').read_text())
        self.checksums(self.new)
        result=subprocess.run(['python3',str(REPO/'scripts/lib.py'),'compose-check',str(self.root),str(self.new)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_compose_rejects_public_bind_and_missing_one_shot_restart(self):
        for settings in ({'host_ip':'0.0.0.0'},{'migration_restart':None}):
            with self.subTest(settings=settings):
                self.settings(**settings)
                result=self.run_script('deploy.sh',self.new)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(any('/app/bin/migrate' in e['args'] for e in self.events()))

if __name__=='__main__':unittest.main()
