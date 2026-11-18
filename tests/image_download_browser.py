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
ICO = struct.pack('<3H4B2H2I', 0, 1, 1, 64, 64, 0, 0, 1, 24, len(PNG), 22) + PNG
ICON_DATA = 'data:image/x-icon;base64,' + base64.b64encode(ICO).decode()
EXTERNAL = 'https://public.test:19202'

with sync_playwright() as p:
    for engine in ('chromium', 'firefox', 'webkit'):
        browser = getattr(p, engine).launch()
        try:
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True, reduced_motion='reduce',
                                          viewport={'width': 1440, 'height': 1050})
            for origin in ('http://127.0.0.1:19120',):
                page = context.new_page()
                remote_requests, image_calls = [], []
                def remote(route):
                    remote_requests.append(route.request.url)
                    route.fulfill(body=PNG, content_type='image/png', headers={'Access-Control-Allow-Origin': '*'})
                def image(route):
                    request = route.request.post_data_json
                    image_calls.append(request)
                    route.fulfill(json={'data_url': ICON_DATA if request['url'] == EXTERNAL + '/icon' else DATA})
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
                markdown = page.locator('[data-slot="aui_markdown-image"]').first
                target = EXTERNAL + '/markdown.png'
                if mode == 'off':
                    assert markdown.locator('img').count() == 0
                    assert page.evaluate('(url) => window.hermesDesktop.saveImageFromUrl(url)', target) is False
                    assert not image_calls and not remote_requests
                else:
                    if mode == 'ask':
                        markdown.get_by_role('button', name='Load once through Tor / retry').click()
                    rendered = markdown.locator('img').first
                    rendered.wait_for()
                    page.wait_for_function("() => [...document.images].some(i => i.alt === 'External fixture image' && i.complete && i.naturalWidth === 64)")
                    displayed_calls = [call for call in image_calls if call['url'] == target]
                    def image_menu(name):
                        # Center the image away from the sticky user message and
                        # click its left side, clear of the overlaid Save button.
                        rendered.evaluate("(image) => image.scrollIntoView({block: 'center'})")
                        rendered.click(button='right', position={'x': 8, 'y': 32})
                        return page.get_by_role('menuitem', name=name, exact=True)
                    unexpected_dialogs = []
                    def unexpected(dialog):
                        unexpected_dialogs.append(dialog.message)
                        dialog.dismiss()
                    page.on('dialog', unexpected)
                    image_menu('Copy image').click()
                    page.wait_for_function('() => clipboardProof.results.length === 1')
                    assert bytes(page.evaluate('clipboardProof.results[0]')) == PNG
                    with page.expect_download() as saved:
                        image_menu('Save image as…').click()
                    assert saved.value.suggested_filename == 'markdown.png'
                    assert Path(saved.value.path()).read_bytes() == PNG
                    if mode != 'browser_native':
                        assert [call for call in image_calls if call['url'] == target] == displayed_calls
                        assert not remote_requests, remote_requests
                    assert not unexpected_dialogs, unexpected_dialogs
                    page.remove_listener('dialog', unexpected)

                    # The toolbar retains the original URL and requests fresh bytes.
                    save = markdown.get_by_role('button', name='Download image', exact=True)
                    if mode == 'ask':
                        before = len(image_calls)
                        page.once('dialog', lambda dialog: dialog.dismiss())
                        assert page.evaluate('(url) => window.hermesDesktop.saveImageFromUrl(url)', target) is False
                        assert len(image_calls) == before
                        def approve(dialog):
                            assert EXTERNAL in dialog.message and 'once through Tor' in dialog.message
                            dialog.accept()
                        page.once('dialog', approve)
                    with page.expect_download() as saved:
                        save.click()
                    assert saved.value.suggested_filename == 'markdown.png'
                    assert Path(saved.value.path()).read_bytes() == PNG
                    if mode == 'browser_native':
                        assert remote_requests and not image_calls
                    else:
                        assert not remote_requests, remote_requests
                        assert [call for call in image_calls if call['url'] == target] == [
                            *displayed_calls, {'url': target, 'load_once': True}]
                        grants = page.evaluate('async () => (await (await fetch("/api/private-content/policy")).json()).origins')
                        assert grants == [], grants
                    if mode == 'tor_proxied':
                        rendered = page.get_by_alt_text('External fixture icon', exact=True)
                        rendered.wait_for()
                        page.wait_for_function("() => [...document.images].some(i => i.alt === 'External fixture icon' && i.complete && i.naturalWidth === 64)")
                        before = len(image_calls)
                        with page.expect_download() as saved:
                            image_menu('Save image as…').click()
                        assert saved.value.suggested_filename == 'icon.ico'
                        assert Path(saved.value.path()).read_bytes() == ICO
                        assert len(image_calls) == before and not remote_requests
                page.close()
            context.close()
            print(f'PASS: {engine} {mode} image Save/Copy bytes, consent and browser request placement', flush=True)
        finally:
            browser.close()
