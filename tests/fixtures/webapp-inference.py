"""Local deterministic inference fixture; no provider calls or outbound network."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import time

MODEL = 'neardirect:z-ai/glm-5.3-flash'


def terminal_answer(request):
    messages = request['messages']
    user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]['role'] == 'user'), None)
    if user_index is None:
        return None
    content = messages[user_index].get('content')
    if isinstance(content, list):
        content = '\n'.join(part.get('text', '') for part in content)
    content = str(content)
    selection = re.search(r'\bqualification-terminal-selection (AGENT-[0-9a-f]+)\b', content)
    if selection is not None:
        selected = re.findall(r'```terminal\n(.*?)\n```', content, re.DOTALL)
        passed = any(selection[1] in block for block in selected)
        return {'content': 'PRIVATE-TERMINAL-SELECTION-' + ('OK' if passed else 'WRONG')}, 'stop'
    probe = re.search(r'\bqualification-terminal-read ((?:CODE|AGENT)-[0-9a-f]+) '
                      r'((?:CODE|AGENT)-[0-9a-f]+) ((?:CODE|AGENT)-[0-9a-f]+) (viewport|scrollback)\b', content)
    if probe is None:
        return None
    marker, other, excluded, view = probe.groups()
    results = [message['content'] for message in messages[user_index + 1:] if message['role'] == 'tool']
    if results:
        result = json.loads(results[-1])
        if marker.startswith('AGENT-'):
            passed = (result.get('error', '').startswith('No window has a readable terminal for this chat.') and
                      not any(value in results[-1] for value in (marker, other, excluded)))
        else:
            text = result.get('text', '')
            passed = (marker in text and other not in text and excluded not in text and
                      (view != 'scrollback' or result.get('start') == 0))
        return {'content': 'PRIVATE-TERMINAL-READ-' + ('OK' if passed else 'WRONG')}, 'stop'
    tools = {item['function']['name'] for item in request.get('tools', [])}
    args = {'start_line': 0, 'count': 16} if view == 'scrollback' else {}
    name = 'read_terminal'
    if name not in tools and 'tool_call' in tools:
        args = {'calls': [{'name': name, 'arguments': args}]}
        name = 'tool_call'
    if name not in tools:
        return {'content': 'PRIVATE-TERMINAL-READ-TOOL-MISSING'}, 'stop'
    return {'tool_calls': [{'index': 0, 'id': f'call_fixture_terminal_{marker}', 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'tool_calls'


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
        terminal = terminal_answer(request)
        if terminal is None:
            deltas = ({'content': 'PRIVATE-CHAT-'}, {'content': 'STREAM-OK'})
            finish = 'stop'
        else:
            delta, finish = terminal
            deltas = (delta,)
        for delta in deltas:
            event = {**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant', **delta},'finish_reason':None}]}
            self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.flush()
            time.sleep(.1)  # Distinct streamed fixture chunks, not a work deadline.
        self.wfile.write(('data: '+json.dumps({**base,'object':'chat.completion.chunk',
            'choices':[{'index':0,'delta':{},'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode())
        self.wfile.flush()
        self.close_connection = True


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0',8337), Handler).serve_forever()
