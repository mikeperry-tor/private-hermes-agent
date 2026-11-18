"""Real renderer Save/Copy controls with controlled image bytes and outbound observation."""
import base64
from pathlib import Path
import sys
import struct
import zlib

from playwright.sync_api import sync_playwright

password, mode = Path(sys.argv[1]).read_text(), sys.argv[2]
def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)


# Give the native overlaid Save button a normal image-sized pointer target.
PNG = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 64, 64, 8, 2, 0, 0, 0)) +
       chunk(b'IDAT', zlib.compress((b'\0' + b'\0\0\xff' * 64) * 64)) + chunk(b'IEND', b''))
DATA = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
EXTERNAL = 'https://public.test:19202'

with sync_playwright() as p:
    for engine in ('chromium', 'firefox', 'webkit'):
        browser = getattr(p, engine).launch()
        try:
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True, reduced_motion='reduce')
            for origin in ('http://127.0.0.1:19120',):
                page = context.new_page()
                remote_requests, image_calls = [], []
                def remote(route):
                    remote_requests.append(route.request.url)
                    route.fulfill(body=PNG, content_type='image/png', headers={'Access-Control-Allow-Origin': '*'})
                def image(route):
                    image_calls.append(route.request.post_data_json)
                    route.fulfill(json={'data_url': DATA})
                # Controlled clipboard sink qualifies the native menu/reader path
                # across engines without claiming OS clipboard permission coverage.
                page.add_init_script("""(() => {
                    window.clipboardProof = {attempts: 0, results: [], errors: []};
                    window.ClipboardItem = class { constructor(items) { this.items = items; } };
                    Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
                        write: async items => {
                            window.clipboardProof.attempts++;
                            try {
                                const blob = await items[0].items['image/png'];
                                window.clipboardProof.results.push(Array.from(new Uint8Array(await blob.arrayBuffer())));
                            } catch (error) {
                                window.clipboardProof.errors.push(String(error)); throw error;
                            }
                        }
                    }});
                })()""")
                page.route(EXTERNAL + '/**', remote)
                page.route('**/api/private-content/image', image)
                page.goto(origin + '/login')
                page.locator('input[name=username]').fill('admin')
                page.locator('input[name=password]').fill(password)
                page.locator('button[type=submit]').click()
                page.wait_for_url(lambda url: '/login' not in url)
                # As in webapp_browser, wait for native gateway boot before
                # interacting with the transcript. Its connecting/onboarding
                # overlay deliberately intercepts input even while REST history
                # and images are already rendered underneath.
                page.get_by_text('ready', exact=True).first.wait_for(timeout=30000)
                page.wait_for_function('''() => {
                    const overlay = document.querySelector('[data-glass-opaque][class*="z-(--z-connecting)"]');
                    return !overlay || getComputedStyle(overlay).pointerEvents === 'none' ||
                        [...document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Continue without setup');
                }''')
                skip = page.get_by_role('button', name='Continue without setup', exact=True)
                if skip.is_visible():
                    skip.click()
                page.locator('[data-glass-opaque][class*="z-(--z-connecting)"]').wait_for(state='hidden')
                page.evaluate('location.hash = "/private-content-qualification"')
                page.get_by_text('Private content qualification message.', exact=False).wait_for(timeout=30000)
                page.wait_for_function('() => Boolean(window.hermesDesktop?.saveImageFromUrl)')
                # Resolve an external source from a visible controlled image.
                # Overriding currentSrc exercises the real context-menu target
                # resolver without triggering a preliminary external image load.
                page.evaluate("""([data, external]) => {
                    const img = document.createElement('img'); img.id = 'clipboard-fixture';
                    img.src = data; img.style = 'position:fixed;top:80px;left:20px;width:64px;height:64px;z-index:9999';
                    Object.defineProperty(img, 'currentSrc', {value: external + '/copy.png'});
                    document.body.append(img);
                }""", [DATA, EXTERNAL])
                def copy_image():
                    page.locator('#clipboard-fixture').click(button='right')
                    page.get_by_role('menuitem', name='Copy image', exact=True).click()
                if mode == 'ask':
                    before = len(image_calls)
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    copy_image()
                    page.wait_for_function('() => clipboardProof.errors.length === 1')
                    assert len(image_calls) == before
                    assert not page.evaluate('clipboardProof.results')
                    page.once('dialog', lambda dialog: dialog.accept())
                copy_image()
                if mode == 'off':
                    page.wait_for_function('() => clipboardProof.errors.length === 1')
                    assert not image_calls and not remote_requests
                else:
                    page.wait_for_function('() => clipboardProof.results.length === 1')
                    assert bytes(page.evaluate('clipboardProof.results[0]')) == PNG
                    if mode != 'browser_native':
                        assert {'url': EXTERNAL + '/copy.png', 'load_once': True} in image_calls
                        assert not remote_requests, remote_requests
                page.locator('#clipboard-fixture').evaluate('(node) => node.remove()')
                if mode == 'off':
                    assert page.evaluate('(url) => window.hermesDesktop.saveImageFromUrl(url)', EXTERNAL + '/save.png') is False
                    assert not image_calls and not remote_requests
                else:
                    if mode == 'ask':
                        # Load-once is independent of the subsequent Save approval.
                        page.get_by_role('button', name='Load once through Tor / retry').first.click()
                        page.wait_for_function('() => [...document.images].some(i => i.src.startsWith("data:image/png") && i.complete)')
                        before = len(image_calls)
                        page.once('dialog', lambda dialog: dialog.dismiss())
                        assert page.evaluate('(url) => window.hermesDesktop.saveImageFromUrl(url)', EXTERNAL + '/cancel.png') is False
                        assert len(image_calls) == before
                        def approve(dialog):
                            assert EXTERNAL in dialog.message and 'once through Tor' in dialog.message
                            dialog.accept()
                        page.on('dialog', approve)
                    page.wait_for_function('() => [...document.images].some(i => i.complete && i.naturalWidth===64)')
                    # Exercise the context-menu entry point with a real click.
                    page.evaluate('''url => {
                        const button = document.createElement('button');
                        button.textContent = 'Save context fixture';
                        button.onclick = () => void window.hermesDesktop.saveImageFromUrl(url);
                        document.body.append(button);
                    }''', EXTERNAL + '/context.png')
                    with page.expect_download() as saved:
                        page.get_by_role('button', name='Save context fixture', exact=True).click()
                    assert saved.value.suggested_filename == 'context.png'
                    assert Path(saved.value.path()).read_bytes() == PNG
                    # Exercise the real Markdown/lightbox Save handler, whose
                    # parent retains the original URL rather than the data URL.
                    markdown = page.locator('[data-slot="aui_markdown-image"]').first
                    if mode == 'ask' and markdown.locator('[data-private-content="image"]').count():
                        markdown.get_by_role('button', name='Load once through Tor / retry').click()
                    save = markdown.get_by_role('button', name='Download image', exact=True)
                    page.evaluate('''() => {
                        const save = window.hermesDesktop.saveImageFromUrl;
                        window.imageSaveCalls = [];
                        window.hermesDesktop.saveImageFromUrl = async src => {
                            const call = {src}; window.imageSaveCalls.push(call);
                            try { return call.result = await save(src); }
                            catch (error) { call.error = String(error); throw error; }
                        };
                    }''')
                    try:
                        with page.expect_download() as saved:
                            save.click()
                    except Exception:
                        print('Save diagnostics:', page.evaluate('window.imageSaveCalls'), image_calls,
                              markdown.evaluate('(node) => node.outerHTML'), flush=True)
                        raise
                    page.wait_for_function('() => imageSaveCalls.length === 1 && imageSaveCalls[0].result === true')
                    assert page.evaluate('imageSaveCalls[0].src') == EXTERNAL + '/markdown.png'
                    assert Path(saved.value.path()).read_bytes() == PNG
                    if mode == 'browser_native':
                        assert remote_requests and not image_calls
                    else:
                        assert not remote_requests, remote_requests
                        assert image_calls[-1]['load_once'] is True
                        grants = page.evaluate('async () => (await (await fetch("/api/private-content/policy")).json()).origins')
                        assert grants == [], grants
                page.close()
            context.close()
            print(f'PASS: {engine} {mode} image Save/Copy bytes, consent and browser request placement', flush=True)
        finally:
            browser.close()
