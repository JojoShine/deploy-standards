"""Opt-in artifact integration: RUN_TEMPLATE_DOCKER_TESTS=1 python3 -m unittest tests/test_template.py.

Requires Docker with linux/amd64 execution. All resources use unique names, synthetic
credentials, an isolated network, and no host port publishing.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('RUN_TEMPLATE_DOCKER_TESTS') == '1', 'opt-in Docker integration')
class TemplateArtifactsTest(unittest.TestCase):
    @classmethod
    def docker(cls, *args):
        result = subprocess.run(['docker', *args], cwd=ROOT, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout.strip()

    @classmethod
    def setUpClass(cls):
        cls.prefix = 'standards-template-' + uuid.uuid4().hex[:12]
        cls.app_image = cls.prefix + '-app:local'
        cls.migrate_image = cls.prefix + '-migrate:local'
        cls.pg = cls.prefix + '-pg'
        cls.containers = []
        cls.url = 'postgresql://starter:synthetic-test-only@database:5432/starter'
        try:
            cls.docker('build', '--platform', 'linux/amd64', '--target', 'runtime',
                       '--build-arg', 'APP_VERSION=artifact-test', '-t', cls.app_image, 'templates/project')
            cls.docker('build', '--platform', 'linux/amd64', '--target', 'migrate',
                       '-t', cls.migrate_image, 'templates/project')
            cls.docker('network', 'create', cls.prefix)
            cls.docker('run', '-d', '--platform', 'linux/amd64', '--name', cls.pg,
                       '--network', cls.prefix, '--network-alias', 'database',
                       '-e', 'POSTGRES_USER=starter', '-e', 'POSTGRES_DB=starter',
                       '-e', 'POSTGRES_PASSWORD=synthetic-test-only', 'postgres:16-alpine')
            cls.containers.append(cls.pg)
            for _ in range(60):
                ready = subprocess.run(['docker', 'exec', cls.pg, 'pg_isready', '-U', 'starter'],
                                       capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise AssertionError('isolated PostgreSQL did not become ready')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for container in cls.containers:
            subprocess.run(['docker', 'rm', '-fv', container], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', cls.prefix], capture_output=True)
        subprocess.run(['docker', 'image', 'rm', cls.app_image, cls.migrate_image], capture_output=True)

    def sql(self, query):
        return self.docker('exec', self.pg, 'psql', '-U', 'starter', '-d', 'starter', '-Atc', query)

    def tool(self, executable):
        self.docker('run', '--rm', '--platform', 'linux/amd64', '--network', self.prefix,
                    '-e', 'DATABASE_URL=' + self.url, self.migrate_image, '/app/bin/' + executable)

    def test_migration_and_bootstrap_repeat_without_resetting_existing_values(self):
        self.tool('migrate')
        self.tool('migrate')
        self.assertEqual(self.sql('SELECT count(*) FROM app_schema_migrations WHERE version = 1'), '1')
        self.tool('bootstrap')
        self.tool('bootstrap')
        self.assertEqual(self.sql("SELECT value FROM starter_settings WHERE key = 'welcome'"),
                         'Deployment starter')
        self.sql("UPDATE starter_settings SET value = 'keep-existing-value' WHERE key = 'welcome'")
        self.tool('migrate')
        self.tool('bootstrap')
        self.assertEqual(self.sql("SELECT value FROM starter_settings WHERE key = 'welcome'"),
                         'keep-existing-value')
        self.assertEqual(self.sql('SELECT count(*) FROM starter_settings'), '1')

    def test_runtime_image_runs_nonroot_with_matching_health_and_version_paths(self):
        user = self.docker('image', 'inspect', self.app_image, '--format', '{{.Config.User}}')
        self.assertNotIn(user, ['', '0', 'root'])
        for index, base_path in enumerate(['', '/starter']):
            name = self.prefix + '-app-' + str(index)
            self.docker('run', '-d', '--platform', 'linux/amd64', '--name', name,
                        '-e', 'BASE_PATH=' + base_path,
                        '-e', 'DATABASE_URL=postgresql://invalid:unused@unreachable.invalid/starter',
                        self.app_image)
            self.containers.append(name)
            for _ in range(30):
                state = self.docker('inspect', name, '--format', '{{.State.Health.Status}}')
                if state == 'healthy':
                    break
                time.sleep(1)
            self.assertEqual(state, 'healthy')
            self.docker('exec', name, '/app/bin/healthcheck')
            body = self.docker('exec', name, 'node', '--input-type=module', '-e',
                               "console.log(await (await fetch('http://127.0.0.1:8080" +
                               base_path + "/version')).text())")
            self.assertEqual(json.loads(body), {'version': 'artifact-test'})
            if base_path:
                status = self.docker('exec', name, 'node', '--input-type=module', '-e',
                                     "console.log((await fetch('http://127.0.0.1:8080/healthz')).status)")
                self.assertEqual(status, '404')
