import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class ConnectionTests(unittest.TestCase):
    def test_encoded_password_becomes_environment_only(self):
        with tempfile.TemporaryDirectory() as t:
            bin=Path(t);program=bin/'psql'
            program.write_text('#!/usr/bin/env python3\nimport os,sys,json\nprint(json.dumps({"args":sys.argv[1:],"host":os.environ["PGHOST"],"db":os.environ["PGDATABASE"],"password":os.environ["PGPASSWORD"],"url_present":"DATABASE_URL" in os.environ}))\n');program.chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],DATABASE_URL='postgresql://app:synthetic%40pass%27word@database:5432/business?schema=public&sslmode=require')
            result=subprocess.run(['python3',str(ROOT/'templates/project/bin/db.py'),'migrate'],env=env,text=True,capture_output=True,check=True)
            data=json.loads(result.stdout)
            self.assertEqual(data['host'],'database');self.assertEqual(data['db'],'business');self.assertEqual(data['password'],"synthetic@pass'word")
            self.assertFalse(data['url_present']);self.assertFalse(any('synthetic' in arg for arg in data['args']))
if __name__=='__main__':unittest.main()
