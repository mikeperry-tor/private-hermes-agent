"""Real browser login/origin/cookie/WebSocket checks against disposable ingress."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

password = Path(sys.argv[1]).read_text()
LOCAL = 'http://127.0.0.1:19120'
PUBLIC = 'https://webapp-test.example.ts.net:10000'
mode = sys.argv[2] if len(sys.argv) > 2 else 'full'
state_file = Path(sys.argv[1]).parent / 'session-state.json'

class Response:
    def __init__(self, value):
        self.status, self._text = value['status'], value['text']
    def text(self):
        return self._text
    def json(self):
        return json.loads(self._text)
    def body(self):
        return self._text.encode()


def fetch(page, path, method='GET', data=None, file_text=None):
    result = page.evaluate("""async (args) => {
      const options={method:args.method};
      if(args.data!==null){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(args.data);}
      if(args.file!==null){const form=new FormData();form.append('file',new Blob([args.file],{type:'text/plain'}),'ingress-test.txt');options.body=form;}
      const response=await window.fetch(args.path,options);
      return {status:response.status,text:await response.text()};
    }""", {'path':path,'method':method,'data':data,'file':file_text})
    return Response(result)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=[
        '--host-resolver-rules=MAP webapp-test.example.ts.net 127.0.0.1', '--no-proxy-server'])
    try:
        if mode != 'full':
            context = browser.new_context(storage_state=str(state_file))
            status = context.request.get(LOCAL + '/api/config').status
            if mode == 'restart':
                assert status == 200, status
                print('PASS: native authenticated session survives gateway restart', flush=True)
            else:
                assert status in (401,403), status
                response = context.request.post(LOCAL + '/auth/password-login', headers={'Origin':LOCAL},
                        data={'provider':'basic','username':'admin','password':password})
                assert response.status == 200, response.status
                print('PASS: password/signing-key rotation rejects old session and admits new credentials', flush=True)
            context.close()
            sys.exit(0)
        for origin in (LOCAL, PUBLIC):
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            chat_frames = []
            page.on('websocket', lambda ws: ws.on('framereceived', lambda frame: chat_frames.append(frame)))
            page.goto(origin + '/login')
            denied_socket = page.evaluate('''async () => await new Promise((resolve,reject) => {
              const socket=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/host-terminal');
              const timer=setTimeout(()=>reject(new Error('unauthenticated socket did not reject')),5000);
              socket.onopen=()=>{clearTimeout(timer);socket.close();reject(new Error('unauthenticated socket accepted'));};
              socket.onerror=()=>{clearTimeout(timer);resolve(true);};
            })''')
            assert denied_socket
            page.locator('input[name=username]').fill('admin')
            page.locator('input[name=password]').fill(password)
            page.locator('button[type=submit]').click()
            page.wait_for_url(lambda url: '/login' not in url, timeout=30000)
            # Newly introduced JSON transfer routes retain operator auth;
            # invalid inputs exercise admission without creating/importing state.
            assert fetch(page, '/api/ops/transfer/chunk', 'POST', {'offset': -1}).status == 400
            assert fetch(page, '/api/ops/transfer/restore', 'POST', {}).status == 404
            assert fetch(page, '/api/peer/health').status == 404
            # Load actual SPA scripts, not just a login redirect.
            page.wait_for_load_state('domcontentloaded')
            assert page.locator('input[name=password]').count() == 0
            blocked = page.evaluate('''async () => {
              const result = new Promise(resolve => {
                document.addEventListener('securitypolicyviolation', e => {
                  if(e.blockedURI.includes('fonts.googleapis.com')) resolve(true);
                });
                setTimeout(()=>resolve(false),3000);
              });
              const link=document.createElement('link'); link.rel='stylesheet';
              link.href='https://fonts.googleapis.com/css2?family=Inter&display=swap&privacy-check=1';
              document.head.appendChild(link); return await result;
            }''')
            assert blocked, 'External font stylesheet was not blocked by CSP'
            cookies = context.cookies()
            sessions = [cookie for cookie in cookies if 'hermes_session_at' in cookie['name']]
            assert sessions and all(c['httpOnly'] and c['sameSite']=='Lax' and c['path']=='/' for c in sessions)
            assert all(c['secure']==origin.startswith('https:') for c in sessions)
            assert all(c['name'].startswith('__Host-')==origin.startswith('https:') for c in sessions)
            # Qualify chat once per ingress instead of before every content case.
            page.get_by_text('ready', exact=True).first.wait_for(timeout=30000)
            editor = page.locator('[data-slot="composer-rich-input"]').first
            editor.fill('qualification-stream')
            editor.press('Enter')
            page.get_by_text('PRIVATE-CHAT-STREAM-OK', exact=False).wait_for(timeout=30000)
            assert any('PRIVATE-CHAT-' in str(frame) for frame in chat_frames), 'No live chat text arrived over WebSocket'
            other = 'https://other.example.ts.net' if origin.startswith('https:') else 'http://127.0.0.1:19121'
            # APIRequestContext includes browser cookies but lets us test forged Origin directly.
            transport = 'https://127.0.0.1:10000' if origin==PUBLIC else origin
            denied = context.request.post(transport + '/api/webapp/socket-ticket?socket=host-terminal',
                    headers={'Origin':other,'Host':origin.split('://')[1],
                             'Cookie':'; '.join(c['name']+'='+c['value'] for c in context.cookies(origin))})
            assert denied.status == 403, denied.status
            ticket = page.evaluate("""async () => {
              const r = await fetch('/api/webapp/socket-ticket?socket=host-terminal', {method:'POST'});
              if (!r.ok) throw new Error('same-origin ticket request failed '+r.status);
              return (await r.json()).ticket;
            }""")
            assert ticket
            result = page.evaluate("""async (ticket) => await new Promise((resolve,reject) => {
              const ws = new WebSocket(location.origin.replace(/^http/,'ws')+'/api/host-terminal?ticket='+encodeURIComponent(ticket));
              ws.binaryType='arraybuffer';
              let output=''; const timer=setTimeout(()=>{ws.close();reject(new Error('terminal stream timed out'));},20000);
              ws.onopen=()=>ws.send("printf 'browser-terminal\\n' > /tmp/webapp-browser-proof; printf 'STREAM-%s\\n' 'READY'\\n");
              ws.onmessage=(event)=>{output+=(typeof event.data==='string'?event.data:new TextDecoder().decode(event.data));if(output.includes('STREAM-READY')){clearTimeout(timer);ws.close();resolve(true);}};
              ws.onerror=()=>{clearTimeout(timer);reject(new Error('authenticated terminal socket rejected'));};
            })""", ticket)
            assert result
            write = fetch(page, '/api/fs/write-text', 'POST',
                          data={'path':'/workspace/webapp-browser-file.txt','content':'browser file proof'})
            assert write.status == 200, (write.status, write.text()[:300])
            read = fetch(page, '/api/fs/read-text?path=/workspace/webapp-browser-file.txt')
            assert read.status == 200 and 'browser file proof' in read.text()
            upload = fetch(page, '/api/chat/file-upload', 'POST', file_text='browser upload proof')
            assert upload.status == 200, (upload.status, upload.text()[:200])
            from urllib.parse import quote
            staged = upload.json()['path']
            download = fetch(page, '/api/fs/download?path='+quote(staged,safe=''))
            assert download.status == 200 and download.body()==b'browser upload proof'
            # Valid session survives reload; signing key and session-token files are persistent.
            page.reload()
            assert '/login' not in page.url
            # Observe the response independently: logout may navigate the SPA
            # before an awaited in-page fetch returns. Keep transport in the
            # browser so simulated HTTPS uses its resolver and cookie domain.
            with page.expect_response(lambda r: r.url == origin + '/auth/logout') as pending_logout:
                page.evaluate("() => { void fetch('/auth/logout', {method:'POST'}); }")
            logout = pending_logout.value
            assert logout.status in (200,302,303)
            assert not [c for c in context.cookies() if 'hermes_session_at' in c['name']]
            # The old SPA may still be redirecting after logout. A fresh page
            # checks the same cleared cookie context without racing navigation.
            page.close()
            page = context.new_page()
            page.goto(origin + '/login')
            assert fetch(page, '/api/config').status in (401,403)
            context.close()
            print('PASS: browser '+('HTTPS' if origin.startswith('https:') else 'localhost')+' login, cookie flags, same-origin enforcement, terminal streaming, SSH file access and logout', flush=True)
        # Browser requests cannot promote localhost to HTTPS by supplying forwarding headers.
        context = browser.new_context()
        response = context.request.post(LOCAL + '/auth/password-login',
                headers={'Origin':LOCAL,'Forwarded':'proto=https;host=attacker.invalid',
                         'X-Forwarded-Proto':'https','X-Forwarded-Host':'attacker.invalid',
                         'X-Forwarded-Prefix':'/attacker','X-Forwarded-For':'127.0.0.1'},
                data={'provider':'basic','username':'admin','password':password})
        assert response.status == 200
        assert all(not c['secure'] and c['path']=='/' for c in context.cookies() if 'hermes_session_at' in c['name'])
        context.storage_state(path=str(state_file))
        state_file.chmod(0o600)
        # Native process-local login throttle: retries through this ingress share its bucket.
        statuses=[]
        for attempt in range(12):
            r=context.request.post(LOCAL+'/auth/password-login', data={'provider':'basic','username':'admin','password':'wrong test password'})
            statuses.append(r.status)
        assert 429 in statuses, statuses
        context.close()
        print('PASS: forged forwarding headers cannot alter cookie scheme/path; native password throttling is active', flush=True)
    finally:
        browser.close()
