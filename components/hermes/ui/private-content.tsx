// Shared browser-hosted resource rendering. The gateway remains authoritative.
import { Children, isValidElement, type ComponentProps, type ReactNode, useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { isBrowserHostedDesktop } from '@/lib/platform'

type Policy = { mode: 'tor_proxied' | 'ask' | 'off' | 'browser_native'; origins: string[]; error?: string }
let policy: Policy | null = null
let pending: Promise<void> | null = null
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
const publish = (next: Policy) => { policy = next; listeners.forEach(listener => listener()) }

async function request(path: string, payload?: object) {
  const response = await fetch('/api/private-content/' + path, {
    credentials: 'same-origin', cache: 'no-store',
    ...(payload ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {})
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Private content is unavailable')
  return data
}

function loadPolicy() {
  if (!pending) {
    pending = request('policy').then(next => {
      if (!['tor_proxied', 'ask', 'off', 'browser_native'].includes(next.mode) || !Array.isArray(next.origins) || !next.origins.every((origin: unknown) => typeof origin === 'string')) {
        throw new Error('Invalid deployment policy')
      }
      publish(next)
    }).catch(() => { publish({ mode: 'off', origins: [], error: 'Could not read external-content policy. Reload this page.' }) })
  }
  return pending
}

export async function browserContentMode() {
  await loadPolicy()
  return policy?.mode || 'off'
}

// Browser image Save and Copy actions use the same transport and
// explicit one-time approval. Never change the shared gateway-file downloader.
export async function privateImageDownloadSource(src: string): Promise<string | null> {
  const url = external(src)
  if (!url) return src
  const mode = await browserContentMode()
  if (mode === 'browser_native') return src
  if (mode === 'off') throw new Error('External images are disabled by deployment policy.')
  if (mode === 'ask' && !window.confirm(`Retrieve this image once through Tor from ${url.origin}? This does not remember permission for the origin.`)) {
    return null
  }
  return (await request('image', { url: url.href, load_once: true })).data_url
}

export function useExternalPolicy() {
  const current = useSyncExternalStore(subscribe, () => policy, () => null)
  useEffect(() => { if (isBrowserHostedDesktop()) void loadPolicy() }, [])
  return current
}

function destination(src: string | undefined) {
  try { return src ? new URL(src, location.href) : null } catch { return null }
}
function external(src: string | undefined) {
  const url = destination(src)
  return url && ['http:', 'https:'].includes(url.protocol) && url.origin !== location.origin ? url : null
}
function passiveLocal(src: string | undefined) {
  const url = destination(src)
  return !src || Boolean(url && (url.origin === location.origin || ['data:', 'blob:'].includes(url.protocol)))
}

function Action({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  // Image consumers can sit inside their native lightbox button. Avoid nested
  // button elements and stop the containing image's activation on this action.
  return <span role="button" tabIndex={0} className="cursor-pointer underline"
    onClick={event => { event.preventDefault(); event.stopPropagation(); onClick() }}
    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); event.stopPropagation(); onClick()
    } }}>{children}</span>
}

export function ExternalFallback({ src, reason }: { src?: string; reason?: string }) {
  const url = external(src)
  return <span data-private-content="blocked" className="block rounded border border-dashed p-3 text-xs">
    <span className="block">{reason || 'This content cannot be loaded privately in the app.'}</span>
    {url && <><span className="block break-all">{url.origin}</span><a className="underline" href={url.href}
      target="_blank" rel="noopener noreferrer" onClick={event => event.stopPropagation()}>Open externally (uses your browser connection)</a></>}
  </span>
}

export function ImagePermissions() {
  const current = useExternalPolicy()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  return <><Action onClick={() => setOpen(true)}>Image permissions</Action>{open && createPortal(
    <div role="dialog" aria-label="Private image permissions" className="fixed inset-8 z-[9999] overflow-auto rounded border bg-background p-6 shadow-xl">
      <button type="button" onClick={() => setOpen(false)}>Close</button>
      <p>Remembered Tor image origins for {location.origin}. Logout and restart retain these permissions.</p>
      {current?.error && <p role="alert">{current.error}</p>}
      {current?.origins.length ? current.origins.map(origin => <p key={origin}>{origin} <button type="button"
        onClick={() => { void request('consent', { origin, remember: false }).then(result => {
          if (policy) publish({ ...policy, origins: result.origins })
        }).catch(error => setError(error.message)) }}>Revoke</button></p>) : <p>No remembered origins.</p>}
      <p>Revocation prevents future retrieval. Already delivered bytes cannot be recalled.</p>
      {error && <p role="alert">{error}</p>}
    </div>, document.body)}</>
}

export function PrivateImage({ src, srcSet, ...props }: ComponentProps<'img'>) {
  const current = useExternalPolicy()
  const url = external(src)
  const origin = url?.origin || ''
  const [result, setResult] = useState({ key: '', data: '', error: '' })
  const key = src + ':' + current?.mode + ':' + current?.origins.includes(origin)
  const approved = current?.mode === 'tor_proxied' || current?.mode === 'browser_native' ||
    (current?.mode === 'ask' && current.origins.includes(origin))
  useEffect(() => {
    let active = true
    if (url && current?.mode !== 'browser_native' && approved) {
      setResult({ key, data: '', error: '' })
      void request('image', { url: url.href, load_once: false }).then(result => {
        if (active) setResult({ key, data: result.data_url, error: '' })
      }).catch(error => { if (active) setResult({ key, data: '', error: error.message }) })
    }
    return () => { active = false }
  }, [key, approved])
  if (!isBrowserHostedDesktop()) return <img {...props} src={src} srcSet={srcSet} />
  if (passiveLocal(src)) return <img {...props} src={src} />
  if (url && current?.mode === 'browser_native') return <img {...props} src={url.href} srcSet={srcSet} />
  if (result.key === key && result.data && current && current.mode !== 'off') return <img {...props} src={result.data} />
  return <span data-private-content="image" className="relative z-10 block rounded border border-dashed bg-background p-3 text-xs">
    <ExternalFallback src={src} reason={current?.error || (current?.mode === 'off' ? 'External images are disabled by deployment policy.' :
      result.key === key && result.error ? result.error : !current ? 'Checking deployment policy…' :
      approved ? 'Fetching image through Tor…' : 'Approve image retrieval through Tor. A unique URL can still reveal that it was viewed.')} />
    {url && current && current.mode !== 'off' && <span className="flex flex-wrap gap-3 p-1">
      <Action onClick={() => { void request('image', { url: url.href, load_once: true }).then(result => {
        setResult({ key, data: result.data_url, error: '' })
      }).catch(error => setResult({ key, data: '', error: error.message })) }}>Load once through Tor / retry</Action>
      {current.mode === 'ask' && !current.origins.includes(origin) && <Action onClick={() => {
        void request('consent', { origin, remember: true }).then(result => {
          if (policy) publish({ ...policy, origins: result.origins })
        }).catch(error => setResult({ key, data: '', error: error.message }))
      }}>Remember this origin for Tor images</Action>}
      <ImagePermissions />
    </span>}
  </span>
}

function externalChild(children: ReactNode): string | undefined {
  for (const child of Children.toArray(children)) {
    if (isValidElement<{ src?: string; children?: ReactNode }>(child)) {
      if ((child.type === 'source' || child.type === 'track') && !passiveLocal(child.props.src)) return child.props.src
      const nested = externalChild(child.props.children)
      if (nested) return nested
    }
  }
}

export function PrivateAudio(props: ComponentProps<'audio'>) {
  const current = useExternalPolicy()
  const remoteChild = externalChild(props.children)
  if (isBrowserHostedDesktop() && current?.mode !== 'browser_native' && (!passiveLocal(props.src) || remoteChild)) {
    return <ExternalFallback src={remoteChild || props.src} reason="External audio playback is unavailable in private modes." />
  }
  return <audio {...props} />
}
export function PrivateVideo(props: ComponentProps<'video'>) {
  const current = useExternalPolicy()
  const remoteChild = externalChild(props.children)
  if (isBrowserHostedDesktop() && current?.mode !== 'browser_native' && (!passiveLocal(props.src) || remoteChild)) {
    return <ExternalFallback src={remoteChild || props.src} reason="External video playback is unavailable in private modes." />
  }
  return <video {...props} poster={current?.mode === 'browser_native' || passiveLocal(props.poster) ? props.poster : undefined} />
}

export function PrivateFrame(props: ComponentProps<'iframe'>) {
  const current = useExternalPolicy()
  const url = destination(props.src)
  const shell = url?.origin === location.origin &&
    ['/assets/webapp-preview.html', '/assets/webapp-guest.html'].includes(url.pathname)
  if (!isBrowserHostedDesktop() || current?.mode === 'browser_native' || (shell && !props.srcDoc)) return <iframe {...props} />
  if (props.srcDoc) return <span className="block"><span className="block text-xs">Inert source preview. Scripts and external dependencies are unavailable in private modes.</span>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap">{props.srcDoc}</pre></span>
  return <ExternalFallback src={props.src} reason="Interactive previews are unavailable in private modes. Downloaded documents may contact external services when opened elsewhere." />
}
