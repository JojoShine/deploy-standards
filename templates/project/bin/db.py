#!/usr/bin/env python3
"""Translate a PostgreSQL URL into libpq environment; never put it in argv."""
import os
import sys
from urllib.parse import parse_qsl, unquote, urlsplit

try:
    uri = urlsplit(os.environ['DATABASE_URL'])
    if uri.scheme not in ('postgres', 'postgresql') or not uri.hostname or not uri.path.strip('/') or uri.fragment:
        raise ValueError('invalid database connection')
    env = {key: value for key, value in os.environ.items() if key != 'DATABASE_URL' and not key.startswith('PG')}
    env.update(PGHOST=uri.hostname, PGPORT=str(uri.port or 5432), PGDATABASE=unquote(uri.path[1:]), PGCONNECT_TIMEOUT='10')
    if uri.username is not None:
        env['PGUSER'] = unquote(uri.username)
    if uri.password is not None:
        env['PGPASSWORD'] = unquote(uri.password)
    options = {'sslmode':'PGSSLMODE','sslrootcert':'PGSSLROOTCERT','sslcert':'PGSSLCERT','sslkey':'PGSSLKEY','channel_binding':'PGCHANNELBINDING','connect_timeout':'PGCONNECT_TIMEOUT'}
    for key,value in parse_qsl(uri.query,keep_blank_values=True):
        if key == 'schema':
            continue
        if key not in options:
            raise ValueError('unsupported database connection option')
        env[options[key]] = value
    script = {'migrate':'/app/sql/migrate.sql','bootstrap':'/app/sql/bootstrap.sql'}[sys.argv[1]]
except (KeyError, ValueError, IndexError):
    raise SystemExit('Invalid database configuration or operation.')
os.execvpe('psql', ['psql','--no-psqlrc','--set=ON_ERROR_STOP=1','--file='+script],env)
