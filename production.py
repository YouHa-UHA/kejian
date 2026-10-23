"""Shared static allowlist and response headers for the classroom application."""
from pathlib import Path

PUBLIC=Path(__file__).resolve().parent/'public'
FILES={
    '/account.mjs':('account.mjs','text/javascript; charset=utf-8'),
    '/ai-ui.mjs':('ai-ui.mjs','text/javascript; charset=utf-8'),
    '/app.mjs':('app.mjs','text/javascript; charset=utf-8'),
    '/apple-touch-icon.png':('apple-touch-icon.png','image/png'),
    '/browser.mjs':('browser.mjs','text/javascript; charset=utf-8'),
    '/comments-ui.mjs':('comments-ui.mjs','text/javascript; charset=utf-8'),
    '/community-ui.mjs':('community-ui.mjs','text/javascript; charset=utf-8'),
    '/confirm-ui.mjs':('confirm-ui.mjs','text/javascript; charset=utf-8'),
    '/deadline-ui.mjs':('deadline-ui.mjs','text/javascript; charset=utf-8'),
    '/homework-ui.mjs':('homework-ui.mjs','text/javascript; charset=utf-8'),
    '/homework.mjs':('homework.mjs','text/javascript; charset=utf-8'),
    '/icon-192.png':('icon-192.png','image/png'),
    '/icon-512.png':('icon-512.png','image/png'),
    '/icon.svg':('icon.svg','image/svg+xml'),
    '/import-ui.mjs':('import-ui.mjs','text/javascript; charset=utf-8'),
    '/':('index.html','text/html; charset=utf-8'),
    '/install.mjs':('install.mjs','text/javascript; charset=utf-8'),
    '/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),
    '/push-sw.js':('push-sw.js','application/manifest+json'),
    '/schedule.mjs':('schedule.mjs','text/javascript; charset=utf-8'),
    '/styles.css':('styles.css','text/css; charset=utf-8'),
    '/workspace.css':('workspace.css','text/css; charset=utf-8'),
    '/index.html':('index.html','text/html; charset=utf-8'),
}
HEADERS=[
    ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),
    ('Referrer-Policy','no-referrer'),('X-Frame-Options','DENY'),
    ('X-Robots-Tag','noindex, nofollow'),
    ('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'; object-src 'none'"),
]
