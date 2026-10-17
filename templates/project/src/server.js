import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';

export function createApp({ basePath = '', version = 'development' } = {}) {
  if (basePath !== '' && !/^\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(basePath)) {
    throw new Error('BASE_PATH must be empty or an absolute path without a trailing slash');
  }
  return createServer((request, response) => {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      response.writeHead(405, { Allow: 'GET, HEAD' });
      response.end();
      return;
    }
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (pathname === `${basePath}/healthz` || pathname === `${basePath}/version`) {
      const payload = pathname.endsWith('/healthz') ? { status: 'ok' } : { version };
      response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify(payload));
    } else if (pathname === `${basePath}/` || (basePath && pathname === basePath)) {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      response.end('<!doctype html><html lang="en"><meta charset="utf-8"><title>Deployment starter</title><h1>Deployment starter</h1><p>Replace this reference application with your business code.</p></html>');
    } else {
      response.writeHead(404);
      response.end();
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createApp({ basePath: process.env.BASE_PATH, version: process.env.APP_VERSION });
  server.listen(Number(process.env.PORT || 8080), '0.0.0.0');
  process.on('SIGTERM', () => server.close(() => process.exit(0)));
  process.on('SIGINT', () => server.close(() => process.exit(0)));
}
