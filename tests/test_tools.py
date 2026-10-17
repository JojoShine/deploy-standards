import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('standards', ROOT / 'tools/standards.py')
standards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(standards)


class ContractTests(unittest.TestCase):
    def test_names_and_refs_reject_shell_and_traversal(self):
        for name in ['../project', 'BadName', 'app; touch /tmp/pwn', '', '-app']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                standards.validate_business(name)
        standards.validate_business('survey-app')
        for sha in ['main', 'a' * 7, 'a' * 39 + ';']:
            with self.assertRaises(ValueError):
                standards.validate_sha(sha)
        for version in ['latest', 'v1.2', 'v01.2.3', 'v1.2.3/evil']:
            with self.assertRaises(ValueError):
                standards.validate_version(version)

    def test_digest_refs_must_be_matching_business_and_service(self):
        good = 'ghcr.io/example/survey-app@sha256:' + 'a' * 64
        standards.validate_image_ref(good, 'survey', 'app')
        for ref in [good.replace('@sha256:', ':latest#'), good.replace('survey-app', 'other-app'), good.replace('ghcr.io', 'evil.test')]:
            with self.assertRaises(ValueError):
                standards.validate_image_ref(ref, 'survey', 'app')

    def test_compose_checks_security_relevant_attributes(self):
        doc = {'services': {'app': {'image': '${APP_IMAGE:?required}', 'restart': 'unless-stopped', 'ports': ['127.0.0.1:${APP_PORT:?required}:8080'], 'healthcheck': {'test': ['CMD', '/app/bin/healthcheck']}, 'environment': {'DATABASE_URL': '${DATABASE_URL:?required}'}}, 'migrate': {'image': '${MIGRATE_IMAGE:?required}', 'profiles': ['ops'], 'restart': 'no', 'environment': {'DATABASE_URL': '${MIGRATION_DATABASE_URL:?required}'}, 'command': ['/app/bin/migrate']}}}
        standards.check_compose(doc)
        for patch in [{'build': '.'}, {'ports': ['${APP_PORT}:8080']}, {'volumes': ['./src:/app']}, {'privileged': True}, {'environment': {'DATABASE_URL': '${DATABASE_URL}', 'ADMIN_PASSWORD': 'bad'}}]:
            broken = json.loads(json.dumps(doc));broken['services']['app'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                standards.check_compose(broken)
        doc['services']['migrate']['ports'] = ['5432:5432']
        with self.assertRaises(ValueError):standards.check_compose(doc)

    def test_generator_pins_ref_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'survey'
            standards.init_project(ROOT, output, 'survey', 'b' * 40, 'example')
            workflow = (output / '.github/workflows/ci.yml').read_text()
            self.assertIn('JojoShine/deploy-standards/.github/workflows/ci.yml@' + 'b' * 40, workflow)
            self.assertNotIn('__BUSINESS__', workflow)
            self.assertTrue((output / 'scripts/deploy.sh').is_file())
            standards.check_callers(output, 'b'*40, 'survey')
            changed=output/'.github/workflows/deploy.yml';changed.write_text(changed.read_text().replace('@'+'b'*40, '@'+'c'*40))
            with self.assertRaises(ValueError):standards.check_callers(output, 'b'*40, 'survey')
            with self.assertRaises(ValueError):standards.init_project(ROOT, output, 'survey', 'b' * 40, 'example')

    def test_bundle_is_deterministic_and_contains_no_env_or_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project';project.mkdir()
            (project / 'compose.prod.yaml').write_text('services: {}\n')
            (project / '.env.prod').write_text('SECRET=must-not-leak\n')
            (project / 'src').mkdir();(project / 'src/private.js').write_text('secret source')
            (project / 'scripts').mkdir();(project / 'scripts/deploy.sh').write_text('#!/bin/bash\nexit 0\n')
            (project / 'scripts/lib.py').write_text('pass\n')
            for name in ['bootstrap.sh','rollback.sh','lib.sh']:(project / 'scripts' / name).write_text('#!/bin/bash\nexit 0\n')
            (project / 'nginx').mkdir();(project / 'nginx/site.conf.example').write_text('# nginx example\n')
            app = 'ghcr.io/example/survey-app@sha256:' + 'a' * 64
            migrate = 'ghcr.io/example/survey-migrate@sha256:' + 'c' * 64
            first = Path(tmp) / 'one.tar.gz';second = Path(tmp) / 'two.tar.gz'
            for output in [first, second]:
                standards.pack_release(project, output, 'survey', 'v1.2.3', 'b' * 40, app, migrate, '', '', 'linux/amd64')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as tar:
                names = tar.getnames()
                self.assertIn('v1.2.3/SHA256SUMS', names)
                self.assertIn('v1.2.3/scripts/lib.py', names)
                self.assertFalse(any('.env.prod' in name or '/src/' in name for name in names))
                metadata = json.load(tar.extractfile('v1.2.3/release.json'))
                self.assertEqual(metadata['images']['app']['ref'], app)
                self.assertEqual(metadata['version'], 'v1.2.3')
                self.assertEqual(metadata['images']['app']['tag'], 'sha-' + 'b'*40)

    def test_bundle_rejects_symlinked_deployment_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project';project.mkdir()
            (project / 'compose.prod.yaml').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                standards.pack_release(project, Path(tmp) / 'release.tar.gz', 'survey', 'v1.2.3', 'b'*40, 'ghcr.io/example/survey-app@sha256:'+'a'*64, 'ghcr.io/example/survey-migrate@sha256:'+'c'*64, '', '', 'linux/amd64')

if __name__ == '__main__':unittest.main()
