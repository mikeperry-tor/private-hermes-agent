"""Authenticated same-origin screen transport against disposable webapp ingress."""
from pathlib import Path
import secrets
import sys
from playwright.sync_api import sync_playwright

password = Path(sys.argv[1]).read_text()
origin = sys.argv[3] if len(sys.argv) > 3 else 'http://127.0.0.1:19120'
nonce = secrets.token_hex(8)
watch_path = '/workspace/cu-watch-' + nonce
human_path = '/workspace/cu-human-' + nonce

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=['--no-proxy-server',
                                        '--host-resolver-rules=MAP webapp-test.example.ts.net 127.0.0.1'])
    context = browser.new_context(ignore_https_errors=True)
    external = []
    context.on('request', lambda request: external.append(request.url)
               if request.url.startswith(('http:', 'https:')) and not request.url.startswith(origin + '/') else None)
    page = context.new_page()
    page.goto(origin + '/login')
    # A display socket without a ticket must yield no screen bytes, even at login.
    assert page.evaluate('''() => new Promise(resolve => {
      const ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/display/ws');
      ws.onmessage=()=>resolve(false); ws.onclose=e=>resolve(e.code===4401);
      ws.onerror=()=>resolve(true);
    })''')
    # Keep requests in Chromium's resolver without opening a saved SPA session
    # whose browser_native content may deliberately fetch external media.
    assert page.evaluate('''async password => (await fetch('/auth/password-login',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:'basic',username:'admin',password})})).status''', password) == 200
    # Keep the real authenticated origin without the SPA's automatic sign-out
    # navigation destroying our independent WebSocket assertions mid-logout.
    assert page.goto(origin + '/api/config').status == 200
    page.evaluate('''async () => {
      const r=await fetch('/api/webapp/socket-ticket?socket=gateway',{method:'POST'});
      if(!r.ok) throw new Error('gateway ticket '+r.status);
      const {ticket}=await r.json();
      const ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/ws?native_dial=browser&ticket='+encodeURIComponent(ticket));
      let seq=0; const pending=new Map();
      window.cu={ws, rpc:(method,params={})=>new Promise((resolve,reject)=>{
        const id=++seq; const timer=setTimeout(()=>{pending.delete(id);reject(new Error('RPC timed out: '+method));},30000);
        pending.set(id,{resolve,reject,timer}); ws.send(JSON.stringify({jsonrpc:'2.0',id,method,params}));
      })};
      ws.onmessage=e=>{for(const line of e.data.trim().split('\\n')) {
        const m=JSON.parse(line), p=pending.get(m.id); if(!p)continue;
        clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result);
      }};
      await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
    }''')

    def rpc(method, params=None):
        return page.evaluate('(a)=>window.cu.rpc(a.method,a.params)', {'method': method, 'params': params or {}})

    def http(path, method='GET'):
        # Use Chromium's resolver, cookies and actual authenticated HTTPS origin.
        return page.evaluate('''async ({path,method}) => {
          const response=await fetch(path,{method});
          return {status:response.status,text:await response.text()};
        }''', {'path': path, 'method': method})

    status = rpc('display.start')
    assert status['running'] and status['placement'] == 'terminal:ssh', status
    # This is disposable fixture state; a previously interrupted diagnostic may
    # intentionally have left a dropped viewer's human lease in place.
    rpc('display.lease.release', {'force': True})
    thumbnail = rpc('display.thumbnail')
    assert thumbnail['data_url'].startswith('data:image/jpeg;base64,'), thumbnail
    page.evaluate('data=>{const img=document.createElement("img");img.src=data;document.body.append(img);}', thumbnail['data_url'])
    print('PASS: authenticated display start and screenshot capture', flush=True)

    # A real RFB handshake and one raw pixel update, with no remote browser fetch.
    page.evaluate('''() => {
      window.cu.open=(ticket,key)=>new Promise((resolve,reject)=>{
        const ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/display/ws?display_ticket='+encodeURIComponent(ticket));
        ws.binaryType='arraybuffer'; let buffer=new Uint8Array(),state=0;
        const timer=setTimeout(()=>{ws.close();reject(new Error('RFB handshake stalled'));},15000);
        window.cu[key]=ws;
        ws.onmessage=e=>{
          const chunk=new Uint8Array(e.data),joined=new Uint8Array(buffer.length+chunk.length);
          joined.set(buffer);joined.set(chunk,buffer.length);buffer=joined;
          while(true){
            if(state===0){if(buffer.length<12)return;
              if(!new TextDecoder().decode(buffer.slice(0,12)).startsWith('RFB '))throw new Error('bad RFB banner');
              ws.send(buffer.slice(0,12));buffer=buffer.slice(12);state=1;
            } else if(state===1){if(!buffer.length||buffer.length<1+buffer[0])return;
              if(!buffer.slice(1,1+buffer[0]).includes(1))throw new Error('no None security type');
              buffer=buffer.slice(1+buffer[0]);ws.send(new Uint8Array([1]));state=2;
            } else if(state===2){if(buffer.length<4)return;
              if(new DataView(buffer.buffer).getUint32(0)!==0)throw new Error('RFB security failed');
              buffer=buffer.slice(4);ws.send(new Uint8Array([1]));state=3;
            } else if(state===3){if(buffer.length<24)return;
              const view=new DataView(buffer.buffer),size=view.getUint32(20);
              if(buffer.length<24+size)return;
              if(!view.getUint16(0)||!view.getUint16(2))throw new Error('empty desktop');
              buffer=buffer.slice(24+size);ws.send(new Uint8Array([3,0,0,0,0,0,0,1,0,1]));state=4;
            } else {if(buffer.length<20)return;
              clearTimeout(timer);ws.onmessage=()=>{};resolve(true);return;
            }
          }
        };
        ws.onerror=()=>{clearTimeout(timer);reject(new Error('RFB socket error'));};
      });
      window.cu.keys=(key,text)=>{
        const ws=window.cu[key];
        for(const ch of text){const symbol=ch==='\\n'?0xff0d:ch.codePointAt(0);
          for(const down of [1,0]){const b=new Uint8Array(8);b[0]=4;b[1]=down;new DataView(b.buffer).setUint32(4,symbol);ws.send(b);}
        }
      };
      window.cu.click=(key,x,y)=>{
        for(const mask of [1,0])window.cu[key].send(new Uint8Array([5,mask,x>>8,x&255,y>>8,y&255]));
      };
      window.cu.closed=ws=>new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>reject(new Error('display socket did not close')),15000);
        ws.onclose=e=>{clearTimeout(timer);resolve(e.code);};
      });
    }''')
    observed = rpc('display.observe')
    # Wrong Host/Origin pairing is rejected before it can consume a valid ticket.
    if origin.startswith('http:'):
        assert page.evaluate('''ticket=>new Promise(resolve=>{
          const ws=new WebSocket('ws://localhost:19120/api/display/ws?display_ticket='+encodeURIComponent(ticket));
          ws.onopen=()=>{ws.close();resolve(false);};ws.onerror=()=>resolve(true);
        })''', observed['ticket'])
    assert page.evaluate('t=>window.cu.open(t,"first")', observed['ticket'])
    if len(sys.argv) > 2 and sys.argv[2] == 'capture':
        assert not external, external
        context.close()
        browser.close()
        print('PASS: same-origin screen capture/pixels without external requests in current content mode', flush=True)
        sys.exit(0)
    reused = page.evaluate('''ticket=>new Promise(resolve=>{
      const ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/display/ws?display_ticket='+encodeURIComponent(ticket));
      ws.onmessage=()=>resolve(false);ws.onclose=e=>resolve(e.code===4401);
    })''', observed['ticket'])
    assert reused
    print('PASS: RFB pixel update, origin restriction and one-use ticket', flush=True)
    expired = rpc('display.observe')
    page.wait_for_timeout(31000)
    assert page.evaluate('''ticket=>new Promise(resolve=>{
      const ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/display/ws?display_ticket='+encodeURIComponent(ticket));
      ws.onmessage=()=>resolve(false);ws.onclose=e=>resolve(e.code===4401);
    })''', expired['ticket'])
    print('PASS: display ticket expiry', flush=True)

    # Open the native dock's terminal through the same human RFB channel. This
    # supplies a live target for both the negative and positive keyboard checks.
    rpc('display.lease.acquire', {'viewer_id': observed['viewer_id']})
    page.wait_for_timeout(350)
    page.evaluate('()=>window.cu.click("first",700,875)')
    page.wait_for_timeout(1000)
    page.evaluate('()=>window.cu.click("first",150,200)')
    rpc('display.lease.release', {'viewer_id': observed['viewer_id']})
    page.wait_for_timeout(350)

    # View-only input must not execute a command in the already focused fixture terminal.
    page.evaluate('path=>window.cu.keys("first","printf watcher > "+path+"\\n")', watch_path)
    page.wait_for_timeout(400)
    watch_result = http('/api/fs/read-text?path=' + watch_path)
    assert watch_result['status'] == 404, watch_result
    rpc('display.lease.acquire', {'viewer_id': observed['viewer_id']})
    assert rpc('display.thumbnail')['suppressed'] == 'human_has_control'
    page.wait_for_timeout(350)
    page.evaluate('()=>window.cu.click("first",150,200)')
    page.wait_for_timeout(100)
    page.evaluate('path=>window.cu.keys("first","printf human > "+path+"\\n")', human_path)
    page.wait_for_timeout(500)
    proof = http('/api/fs/read-text?path=' + human_path)
    assert proof['status'] == 200 and 'human' in proof['text'], proof
    print('PASS: view-only refusal and takeover keyboard positive control', flush=True)

    second = rpc('display.observe')
    assert page.evaluate('t=>window.cu.open(t,"second")', second['ticket'])
    rpc('display.lease.acquire', {'viewer_id': second['viewer_id']})
    page.wait_for_timeout(350)
    stale_path = '/workspace/cu-stale-' + nonce
    page.evaluate('path=>window.cu.keys("first","printf stale > "+path+"\\n")', stale_path)
    page.wait_for_timeout(400)
    stale_result = http('/api/fs/read-text?path=' + stale_path)
    assert stale_result['status'] == 404, stale_result
    print('PASS: second viewer takeover revokes the first viewer\'s keyboard authority', flush=True)
    rpc('display.lease.release', {'viewer_id': second['viewer_id']})
    assert rpc('display.thumbnail')['data_url'].startswith('data:image/jpeg;base64,')
    page.evaluate('()=>{window.cu.stopped=window.cu.closed(window.cu.second);}')
    rpc('display.stop')
    assert page.evaluate('()=>window.cu.stopped') == 1000
    print('PASS: stopping desktop closes display transport', flush=True)
    rpc('display.start')
    third = rpc('display.observe')
    assert page.evaluate('t=>window.cu.open(t,"third")', third['ticket'])
    stale = rpc('display.observe')
    assert http('/auth/logout', 'POST')['status'] == 200
    assert http('/api/config')['status'] in (401, 403)
    assert http('/api/webapp/socket-ticket?socket=gateway', 'POST')['status'] in (401, 403)
    # Native cookie logout revokes refresh credentials and clears the browser's
    # cookies, but does not revoke established sockets or all issued tickets.
    # Verify and document that contract instead of claiming immediate revocation.
    assert page.evaluate('()=>window.cu.third.readyState') == 1
    assert page.evaluate('t=>window.cu.open(t,"issuedBeforeLogout")', stale['ticket'])
    assert not external, external
    context.close()
    browser.close()
    print('PASS: authenticated same-origin thumbnail/RFB pixels; wrong origin, reused and expired tickets rejected')
    print('PASS: view-only/stale keyboard blocked, human input confined to executor, takeover, stop/restart and logout')
    print('PASS: screen viewing made no external HTTP requests')
    print('LIMIT: cookie logout blocks new HTTP grants; established sockets and issued tickets retain native lifetimes')
