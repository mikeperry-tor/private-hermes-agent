"""Stateless Streamable HTTP MCP fixture, plus reachable forbidden-port controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import threading
import socket


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path.startswith('/relay/'):
            if self.headers.get('X-Hermes-Session-Token') != 'disposable-relay-token':
                self.send_error(401)
                return
            if self.path == '/relay/image.png':
                mime = 'image/png'
                body = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC')
            elif self.path == '/relay/image.svg':
                mime = 'image/svg+xml'
                body = b'<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("https://public.test:19202/relay-script")</script><image href="https://public.test:19202/relay.png"/></svg>'
            else:
                mime = 'text/html'
                body = b'<script>fetch("https://public.test:19202/relay-script")</script><img src="https://public.test:19202/relay.png">'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            # An upstream gateway cannot declare its document a trusted local page.
            self.send_header('X-Private-Hermes-Trusted-Page', '1')
            self.send_header('Set-Cookie', 'relay-must-not-cross=1')
            self.send_header('Link', '<https://public.test:19202>; rel=preconnect')
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/mcp':
            self.send_response(405)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if 'id' not in request:
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        method = request['method']
        if method == 'initialize':
            result = {'protocolVersion': request['params']['protocolVersion'],
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'isolation-fixture', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': 'echo', 'description': 'Echo test text',
                       'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}]}
        elif method == 'tools/call':
            result = {'content': [{'type': 'text', 'text': request['params']['arguments']['text']}], 'isError': False}
        else:
            result = {}
        data = ('event: message\ndata: ' + json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}) + '\n\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()


def udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(('0.0.0.0', 111))
        while True:
            _, address = server.recvfrom(1024)
            server.sendto(b'rpcbind-open', address)

if __name__ == '__main__':
    for port in (111, 8000, 8001):
        server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=udp, daemon=True).start()
    threading.Event().wait()
