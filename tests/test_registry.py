import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import registry

class RegistryTests(unittest.TestCase):
    def test_formal_tag_cannot_be_overwritten(self):
        with patch.object(registry,'descriptor',return_value={'digest':'sha256:'+'a'*64}), patch.object(registry.subprocess,'run') as run:
            with self.assertRaises(ValueError):registry.promote('ghcr.io/example/app@sha256:'+'b'*64,'ghcr.io/example/app:v1.0.0')
            run.assert_not_called()
    def test_same_formal_digest_is_idempotent(self):
        with patch.object(registry,'descriptor',return_value={'digest':'sha256:'+'a'*64}), patch.object(registry.subprocess,'run') as run:
            registry.promote('ghcr.io/example/app@sha256:'+'a'*64,'ghcr.io/example/app:v1.0.0');run.assert_not_called()
    def test_promote_must_preserve_exact_manifest(self):
        with patch.object(registry,'descriptor',side_effect=[None,{'digest':'sha256:'+'b'*64}]),patch.object(registry.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):registry.promote('ghcr.io/example/app@sha256:'+'a'*64,'ghcr.io/example/app:v1.0.0')
            self.assertIn('--prefer-index=false',run.call_args.args[0])
if __name__=='__main__':unittest.main()
