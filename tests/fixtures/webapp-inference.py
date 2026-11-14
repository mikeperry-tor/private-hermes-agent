"""Local deterministic inference fixture; no provider calls or outbound network."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time

MODEL = 'neardirect:z-ai/glm-5.3-flash'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def reply(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == '/health':
            self.reply({'ok': True})
        elif self.path == '/v1/models':
            self.reply({'object':'list','data':[{'id':MODEL,'object':'model','owned_by':'fixture'}]})
        else:
            self.reply({'error':'Unsupported fixture endpoint'}, 404)
    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.reply({'error':'Unsupported fixture endpoint'}, 400)
            return
        request = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        base = {'id':'fixture-completion','object':'chat.completion','created':int(time.time()),'model':MODEL}
        if not request.get('stream'):
            self.reply({**base,'choices':[{'index':0,'message':{'role':'assistant','content':'Qualification'},'finish_reason':'stop'}],
                        'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
            return
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Connection','close')
        self.end_headers()
        for text in ('PRIVATE-CHAT-', 'STREAM-OK'):
            event = {**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]}
            self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.flush()
            time.sleep(.1)  # Distinct streamed fixture chunks, not a work deadline.
        self.wfile.write(('data: '+json.dumps({**base,'object':'chat.completion.chunk',
            'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode())
        self.wfile.flush()
        self.close_connection = True


ThreadingHTTPServer(('0.0.0.0',8337), Handler).serve_forever()
