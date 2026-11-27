"""Response enforcement for the browser app and every separately served document."""
import base64
import hashlib
import os
from pathlib import Path
import sys

try:
    from hermes_cli.private_addressing import Addresses, network_prefix
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
    from addressing import Addresses, network_prefix
from hermes_cli.private_external_content import deployment_mode

INERT_PREVIEW = '''<!doctype html><meta charset="utf-8"><title>Inert preview</title>
<p>Inert source preview. Scripts, external dependencies and interactive plugins
are unavailable in private modes. Downloaded documents may contact external
services when opened elsewhere.</p><pre id="source" style="white-space:pre-wrap"></pre>
<script>
addEventListener('message', event => {
  if (event.source === parent && parent !== window &&
      event.origin === new URL(location.href).origin &&
      event.data?.type === 'hermes-preview-document' && typeof event.data.html === 'string') {
    document.getElementById('source').textContent = event.data.html;
    parent.postMessage({type: 'hermes-guest-loaded'}, '*');
  }
});
</script>'''
_SCRIPT = INERT_PREVIEW.split('<script>', 1)[1].split('</script>', 1)[0]
_HASH = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
INERT_POLICY = (f"default-src 'none'; script-src 'sha256-{_HASH}'; script-src-attr 'none'; "
                "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'self'; sandbox allow-scripts")


def private_preview():
    if deployment_mode() == 'browser_native':
        return None
    from fastapi.responses import HTMLResponse
    return HTMLResponse(INERT_PREVIEW, headers={
        'Content-Security-Policy': INERT_POLICY,
        'X-Private-Hermes-Trusted-Page': '1',
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-DNS-Prefetch-Control': 'off',
    })


class PrivateContentMiddleware:
    def __init__(self, app):
        self.app = app
        self.mode = deployment_mode()
        self.backend_ip = Addresses(network_prefix(os.environ)).agent_webapp_backend

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_headers = dict(scope.get('headers', []))
        ingress_mode = request_headers.get(b'x-private-hermes-content-mode')
        # Uvicorn may normalize the client through trusted forwarding headers;
        # the accepted socket's local address still identifies fixed ingress.
        ingress_socket = scope.get('server', (None, None))[0] == self.backend_ip
        if ((ingress_socket and ingress_mode is None) or
                (ingress_mode is not None and ingress_mode.decode('ascii', 'replace') != self.mode)):
            from starlette.responses import PlainTextResponse
            return await PlainTextResponse('Content policy mismatch: recreate gateway and ingress', status_code=503)(scope, receive, send)
        private = self.mode != 'browser_native'
        host = request_headers.get(b'host', b'').decode('ascii', 'replace')
        websocket = ('wss' if scope['scheme'] == 'https' else 'ws') + '://' + host
        # Additive policy: do not replace native script hashes or other headers.
        policy = ("img-src 'self' data: blob:; media-src 'self' data: blob:; "
                  f"connect-src 'self' {websocket} data: blob:; "
                  "frame-src 'self' blob:; worker-src 'self' blob:; "
                  "font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                  "object-src 'none'; base-uri 'none'; form-action 'self'")

        async def guarded(message):
            if private and message['type'] == 'http.response.early_hint':
                return  # Untrusted hints must never precede the restrictive document.
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                values = dict(headers)
                trusted_page = values.get(b'x-private-hermes-trusted-page') == b'1'
                headers = [(key, value) for key, value in headers if key.lower() not in (
                    b'x-private-hermes-trusted-page', b'referrer-policy', b'x-dns-prefetch-control')
                    and not (private and key.lower() in (b'link', b'refresh'))]
                headers += [(b'referrer-policy', b'no-referrer'), (b'x-dns-prefetch-control', b'off')]
                if private:
                    headers.append((b'content-security-policy', policy.encode('ascii')))
                mime = values.get(b'content-type', b'').split(b';', 1)[0].lower()
                # Main SPA/handoff pages are marked by native page_headers.
                # Login and auth callbacks are native trusted documents.
                path = scope.get('path', '')
                native_auth = (path == '/login' or path.startswith('/auth/') or path.startswith('/api/mcp/oauth/callback/')
                               or path in ('/assets/webapp-preview.html', '/assets/webapp-guest.html'))
                if mime in (b'text/html', b'application/xhtml+xml', b'image/svg+xml') and not (trusted_page or native_auth):
                    headers = [(key, value) for key, value in headers if key.lower() not in (
                        b'content-type', b'content-disposition', b'x-content-type-options')]
                    # Linux WebKit can render attachment HTML inline. Binary
                    # delivery preserves downloads without relying on that hint.
                    headers += [(b'content-type', b'application/octet-stream'),
                                (b'content-disposition', b'attachment'),
                                (b'x-content-type-options', b'nosniff'),
                                (b'content-security-policy', b"sandbox; default-src 'none'; base-uri 'none'; form-action 'none'")]
                message = {**message, 'headers': headers}
            await send(message)
        return await self.app(scope, receive, guarded)
