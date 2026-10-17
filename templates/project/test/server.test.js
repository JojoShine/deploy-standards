import assert from 'node:assert/strict';
import { once } from 'node:events';
import { test } from 'node:test';
import { createApp } from '../src/server.js';

async function withApp(options, callback) {
  const server = createApp(options);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    await callback(`http://127.0.0.1:${server.address().port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('root deployment answers health without a database connection', async () => {
  await withApp({ basePath: '', version: 'test-commit' }, async (origin) => {
    const response = await fetch(`${origin}/healthz`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: 'ok' });
  });
});

test('path deployment keeps health and version under the configured prefix', async () => {
  await withApp({ basePath: '/starter', version: 'abc123' }, async (origin) => {
    const health = await fetch(`${origin}/starter/healthz`);
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), { status: 'ok' });
    const version = await fetch(`${origin}/starter/version`);
    assert.equal(version.status, 200);
    assert.deepEqual(await version.json(), { version: 'abc123' });
    assert.equal((await fetch(`${origin}/healthz`)).status, 404);
    assert.equal((await fetch(`${origin}/starter-other/healthz`)).status, 404);
  });
});

test('starter page is served at the configured app root', async () => {
  await withApp({ basePath: '/starter', version: 'test' }, async (origin) => {
    const response = await fetch(`${origin}/starter/`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type'), /text\/html/);
    assert.match(await response.text(), /Deployment starter/);
  });
});

test('write requests cannot report successful health', async () => {
  await withApp({ basePath: '', version: 'test' }, async (origin) => {
    assert.equal((await fetch(`${origin}/healthz`, { method: 'POST' })).status, 405);
  });
});

test('invalid path prefixes fail before listening', () => {
  for (const basePath of ['starter', '/starter/', '//starter', '/a?b', '/a#b', '/a/../b']) {
    assert.throws(() => createApp({ basePath, version: 'test' }), /BASE_PATH/);
  }
});
