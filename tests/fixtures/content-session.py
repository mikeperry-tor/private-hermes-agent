"""Seed disposable native model/tool output without inference or paid calls."""
import json
import sys
from hermes_state import SessionDB

PUBLIC = 'https://public.test:19202'
SESSION = 'private-content-qualification'
db = SessionDB()
if db.get_session(SESSION) is None:
    db.create_session(SESSION, 'cli', cwd='/workspace')
    db.append_message(SESSION, 'user', 'Show the disposable browser privacy qualification content.')
    db.append_message(SESSION, 'assistant', tool_calls=[{
        'id': 'fixture-image-tool', 'type': 'function',
        'function': {'name': 'image_generate', 'arguments': json.dumps({'prompt': 'fixture'})},
    }])
    db.append_message(SESSION, 'tool', tool_name='image_generate', tool_call_id='fixture-image-tool',
                      content=json.dumps({'success': True, 'image': PUBLIC + '/generated.png'}))
    icon = f'![External fixture icon]({PUBLIC}/icon)' if '--download-icon' in sys.argv else ''
    db.append_message(SESSION, 'assistant', content=f'''Private content qualification message.

![External fixture image]({PUBLIC}/markdown.png)

{icon}

![Local fixture image](/workspace/private-content-local.png)

![External fixture video]({PUBLIC}/remote.mp4)

![External fixture audio]({PUBLIC}/remote.wav)

![Local fixture audio](/workspace/private-content-local.wav)

![Local fixture video](/workspace/private-content-local.mp4)

[Privacy deliberate external link]({PUBLIC}/deliberate)

https://www.youtube.com/watch?v=abcdefghijk

```html
<!doctype html><title>Private preview fixture</title>
<link rel="dns-prefetch" href="//private-hint.invalid">
<link rel="preconnect" href="{PUBLIC}">
<style>@import url('{PUBLIC}/preview.css');body{{background:url('{PUBLIC}/css.png')}}</style>
<img src="{PUBLIC}/preview.png">
<video poster="{PUBLIC}/poster.png"><source src="{PUBLIC}/video.m3u8"><track src="{PUBLIC}/subtitles.vtt"></video>
<iframe src="{PUBLIC}/nested"></iframe>
<script>fetch('{PUBLIC}/fetch');new Worker('{PUBLIC}/worker.js');
new RTCPeerConnection({{iceServers:[{{urls:'stun:public.test:3478'}}]}});
location.href='{PUBLIC}/navigation';</script>
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="blue"/><image href="{PUBLIC}/svg-image.png"/></svg>
```
''')
    db.end_session(SESSION, 'qualification')
db.close()
print('Seeded disposable model/tool content session')

# Real enabled plugin assets exercise direct/new-tab active-document responses.
from pathlib import Path
import hermes_yaml as yaml
plugin = Path('/opt/data/plugins/privacy-assets')
assets = plugin / 'dashboard'
assets.mkdir(parents=True, exist_ok=True)
(plugin / 'plugin.yaml').write_text('name: privacy-assets\nversion: "1.0"\ndescription: Disposable browser assets\n')
(plugin / '__init__.py').write_text('def register(ctx): pass\n')
(assets / 'manifest.json').write_text(json.dumps({'name':'privacy-assets','label':'Fixture assets','entry':'entry.js','tab':{'hidden':True}}))
(assets / 'entry.js').write_text('// No automatic fixture behavior.\n')
(assets / 'active.html').write_text('<!doctype html><img src="'+PUBLIC+'/plugin.png"><script>fetch("'+PUBLIC+'/plugin-fetch");location.href="'+PUBLIC+'/plugin-navigation"</script>')
(assets / 'active.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="'+PUBLIC+'/plugin-svg.png"/><script>fetch("'+PUBLIC+'/plugin-svg-fetch")</script></svg>')
config_path = Path('/opt/data/config.yaml')
config = yaml.safe_load(config_path.read_text())
enabled = config.setdefault('plugins',{}).setdefault('enabled',[])
if 'privacy-assets' not in enabled:
    enabled.append('privacy-assets')
    config_path.write_text(yaml.safe_dump(config,sort_keys=False))
