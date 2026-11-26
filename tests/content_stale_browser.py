"""One live browser document across gateway restart and a stricter policy."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

password = Path(sys.argv[1]).read_text()
ORIGIN = 'http://127.0.0.1:19120'
EXTERNAL = 'https://public.test:19202'


def fetch(page, path, payload=None):
    return page.evaluate('''async ({path,payload}) => {
      const response=await fetch(path,payload===null?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      return {status:response.status,body:await response.json()};
    }''', {'path':path,'payload':payload})


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        def login():
            page.goto(ORIGIN+'/login')
            page.locator('input[name=username]').fill('admin')
            page.locator('input[name=password]').fill(password)
            page.locator('button[type=submit]').click()
            page.wait_for_url(lambda url:'/login' not in url)
        login()
        assert fetch(page,'/api/private-content/policy')['body']['mode']=='ask'
        assert fetch(page,'/api/private-content/consent',{'origin':EXTERNAL,'remember':True})['status']==200
        print('READY_RESTART',flush=True)
        assert input()=='restart'
        # Existing native cookie and remembered permission survive recreation.
        assert EXTERNAL in fetch(page,'/api/private-content/policy')['body']['origins']
        assert page.evaluate("() => fetch('/auth/logout',{method:'POST'}).then(r=>r.status)") in (200, 204)
        page.goto('about:blank')
        login()
        assert EXTERNAL in fetch(page,'/api/private-content/policy')['body']['origins']
        assert fetch(page,'/api/private-content/consent',{'origin':EXTERNAL,'remember':False})['status']==200
        assert fetch(page,'/api/private-content/image',{'url':EXTERNAL+'/revoked.png'})['status']==403
        assert fetch(page,'/api/private-content/consent',{'origin':EXTERNAL,'remember':True})['status']==200
        print('READY_OFF',flush=True)
        assert input()=='off'
        # Keep this old ask document alive. Newly forbidden backend operations
        # must fail even though its client-side policy snapshot is stale.
        state=fetch(page,'/api/private-content/policy')
        assert state['status']==200 and state['body']['mode']=='off'
        assert EXTERNAL in state['body']['origins']
        for once in (False,True):
            assert fetch(page,'/api/private-content/image',{'url':EXTERNAL+'/stale.png','load_once':once})['status']==403
        assert fetch(page,'/api/private-content/consent',{'origin':EXTERNAL,'remember':True})['status']==403
        assert fetch(page,'/api/private-content/consent',{'origin':EXTERNAL,'remember':False})['status']==200
        print('PASS: remembered consent survives logout/restart; revocation and off deny stale-page retrieval and approval',flush=True)
    finally:
        browser.close()
