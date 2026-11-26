"""Local deterministic inference fixture; no provider calls or outbound network."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import time
from urllib.parse import quote

MODEL = 'neardirect:z-ai/glm-5.3-flash'


def current_turn(request):
    messages = request['messages']
    user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]['role'] == 'user'), None)
    if user_index is None:
        return '', []
    content = messages[user_index].get('content')
    if isinstance(content, list):
        content = '\n'.join(part.get('text', '') for part in content)
    return str(content), [message['content'] for message in messages[user_index + 1:] if message['role'] == 'tool']


def call_tool(request, name, args, call_id, failure):
    tools = {item['function']['name'] for item in request.get('tools', [])}
    if name not in tools and 'tool_call' in tools:
        args = {'calls': [{'name': name, 'arguments': args}]}
        name = 'tool_call'
    if name not in tools:
        return {'content': failure}, 'stop'
    return {'tool_calls': [{'index': 0, 'id': call_id, 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'tool_calls'


def terminal_answer(request):
    content, results = current_turn(request)
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
    args = {'start_line': 0, 'count': 16} if view == 'scrollback' else {}
    return call_tool(request, 'read_terminal', args, f'call_fixture_terminal_{marker}',
                     'PRIVATE-TERMINAL-READ-TOOL-MISSING')


def project_answer(request):
    content, results = current_turn(request)
    matched = re.search(r'\bqualification-project-(edit|approval) (cli|web) ([0-9a-f]{12})\b', content)
    if matched is None:
        return None
    probe, client, nonce = matched.groups()
    project = '/mnt/projects/shared project'
    target = f'{project}/{client}-{nonce}.txt'
    executable = f'{project}/{client}-executable.sh'
    output = f'PRIVATE-PROJECT-{probe.upper()}'
    if probe == 'approval':
        edits = [('patch', {'path': f'{project}/AGENTS.md', 'old_string': 'Protected fixture',
                            'new_string': 'Changed without review'}, 'agent-instruction file')]
    else:
        edits = [
            ('write_file', {'path': target, 'content': 'created by the model\n'}, 'verified'),
            ('patch', {'path': target, 'old_string': 'created', 'new_string': 'patched'}, 'success'),
            ('patch', {'path': executable, 'old_string': 'host executable',
                       'new_string': f'{client} model edit'}, 'success'),
            ('write_file', {'path': f'{project}-sibling/blocked-{nonce}.txt',
                            'content': 'outside the share'}, 'outside the applied SSH workspace roots'),
            ('patch', {'path': f'{project}/read-only/file.txt', 'old_string': 'unchanged',
                       'new_string': 'unexpected write'}, 'cannot write'),
        ]
    for (_, _, expected), prior in zip(edits, results):
        parsed = json.loads(prior)
        confirmed = parsed.get(expected) is True if expected in {'success', 'verified'} else expected in parsed.get('error', '')
        if not confirmed:
            return {'content': f'{output}-WRONG-{client}-{nonce}'}, 'stop'
    if len(results) == len(edits):
        reply = f'{output}-OK-{client}-{nonce}'
        if client == 'web' and probe == 'approval':
            editor = quote(f'{project}/editor-executable.sh')
            reply += f'\n\n[Open the editor fixture](file://{editor})'
        return {'content': reply}, 'stop'
    name, args, _ = edits[len(results)]
    return call_tool(request, name, args, f'call_project_{client}_{nonce}_{len(results)}',
                     f'{output}-TOOL-MISSING-{client}-{nonce}')


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
        answer = project_answer(request) or terminal_answer(request)
        if not request.get('stream'):
            message, finish = answer or ({'content': 'Qualification'}, 'stop')
            self.reply({**base,'choices':[{'index':0,'message':{'role':'assistant', **message},'finish_reason':finish}],
                        'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
            return
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Connection','close')
        self.end_headers()
        if answer is None:
            deltas = ({'content': 'PRIVATE-CHAT-'}, {'content': 'STREAM-OK'})
            finish = 'stop'
        else:
            delta, finish = answer
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', default='0.0.0.0')
    args = parser.parse_args()
    ThreadingHTTPServer((args.bind, 8337), Handler).serve_forever()
