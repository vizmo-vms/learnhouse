'use client'

import React from 'react'

type PreviewKind = 'html' | 'mermaid'

const MAX_PREVIEW_LENGTH = 40_000
const PREVIEW_CSP = "default-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; connect-src 'none'; worker-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:"

const LEARNING_UI_STYLES = `
:root{color-scheme:light;--lh-accent:#007d83;--lh-accent-soft:#e7f5f4;--lh-text:#18343b;--lh-muted:#52666d;--lh-surface:#fff;--lh-border:#d8e5e7;--lh-radius:12px;--lh-space:16px}
body{padding:20px;color:var(--lh-text);background:#f3f8f8;font:15px/1.55 system-ui,-apple-system,sans-serif;overflow-wrap:anywhere}
main,.lh-demo{max-width:760px;margin:auto}
h1,h2,h3,p{margin:0 0 12px}h1,h2,h3{line-height:1.25;letter-spacing:-.025em}h1,h2{font-size:clamp(20px,4vw,26px)}h3{font-size:17px}
button,input,select,textarea{font:inherit}input,select,textarea{max-width:100%;min-width:0}button,select,input:not([type=range]):not([type=checkbox]):not([type=radio]),textarea{border:1px solid var(--lh-border);border-radius:8px;min-height:44px;background:var(--lh-surface);color:var(--lh-text);padding:10px 14px}
button{font-weight:600;cursor:pointer;transition:background .15s,border-color .15s}button:hover:not(:disabled){border-color:var(--lh-accent);background:var(--lh-accent-soft)}button:disabled{opacity:.55;cursor:default}
:is(button,input,select,textarea):focus-visible{outline:3px solid var(--lh-accent);outline-offset:3px}
input[type=range],input[type=radio],input[type=checkbox]{accent-color:var(--lh-accent)}input[type=range]{width:100%}label{font-weight:600}svg{max-width:100%;height:auto}
.lh-eyebrow{margin-bottom:8px;color:var(--lh-accent);font-size:11px;font-weight:750;letter-spacing:.1em;text-transform:uppercase}.lh-muted{color:var(--lh-muted);font-size:14px}
.lh-card{padding:20px;border:1px solid var(--lh-border);border-radius:var(--lh-radius);background:var(--lh-surface);box-shadow:0 2px 8px #18343b06}
.lh-stack{display:flex;flex-direction:column;gap:var(--lh-space)}.lh-stack>*{margin-block:0}.lh-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:var(--lh-space)}.lh-actions{display:flex;flex-wrap:wrap;gap:8px}
.lh-primary,.lh-primary:hover:not(:disabled){background:var(--lh-accent);border-color:var(--lh-accent);color:#fff}
button[aria-pressed=true],[data-state=selected]{border-color:var(--lh-accent);background:var(--lh-accent-soft);color:var(--lh-text)}
.lh-feedback{padding:12px 14px;border-radius:8px;background:var(--lh-accent-soft);border:1px solid var(--lh-border)}.lh-feedback:empty{padding:0;border:0}
[data-state=correct],button[data-state=correct],button[data-state=correct]:hover,.lh-primary[data-state=correct]:hover{color:#185738;background:#edf8f1;border-color:#a8d7b9}
[data-state=incorrect],button[data-state=incorrect],button[data-state=incorrect]:hover,.lh-primary[data-state=incorrect]:hover{color:#873817;background:#fff3eb;border-color:#e8bc9f}
progress{width:100%;height:8px;accent-color:var(--lh-accent)}small{color:var(--lh-muted)}
@media(max-width:480px){body{padding:12px}.lh-card{padding:16px}.lh-actions>button{flex:1 1 120px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
`

export function buildHtmlPreviewDocument(source: string, kind: PreviewKind = 'html'): string {
  const styles = kind === 'html' ? LEARNING_UI_STYLES : 'body{padding:12px;display:grid;place-items:center;min-height:100vh}svg{max-width:100%;height:auto}'
  const errorHandler = kind === 'html' ? `<script>window.addEventListener('error',()=>{
    if(document.getElementById('lh-preview-error'))return;
    const notice=document.createElement('p');
    notice.id='lh-preview-error';notice.className='lh-feedback';
    notice.setAttribute('role','alert');notice.setAttribute('data-state','incorrect');
    notice.textContent='This exercise could not load. Ask AI for a complete version.';
    document.body.append(notice);
  });</script>` : ''
  const innerDocument = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">${errorHandler}<style>html,body{margin:0;min-height:100%;font-family:system-ui,sans-serif}*{box-sizing:border-box}${styles}</style></head><body>${source}</body></html>`
  const escapedDocument = innerDocument.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // The trusted outer policy also governs navigation of the generated frame.
  // A CSP inside generated HTML alone cannot stop it navigating itself.
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}"><style>html,body{margin:0;height:100%}iframe{display:block;width:100%;height:100%;border:0}</style></head><body><iframe title="Interactive content" sandbox="allow-scripts" referrerpolicy="no-referrer" srcdoc="${escapedDocument}"></iframe></body></html>`
}

let mermaidPromise: Promise<typeof import('mermaid').default> | undefined

export function isSupportedMermaidSource(source: string): boolean {
  // Mermaid prepares SVG in the app document. Only plain diagrams may reach it;
  // image nodes and custom CSS can otherwise fetch resources before isolation.
  const plainDiagram = /^(?:(?:graph|flowchart)\s+(?:TB|TD|BT|RL|LR)\b|sequenceDiagram\b|stateDiagram(?:-v2)?\b|classDiagram\b|erDiagram\b|pie\b|mindmap\b|timeline\b)/
  const resourceOrConfig = /%%\s*\{|@\s*\{|\\|&|#[^;\r\n]{1,32};|!\s*\[|<\s*[a-z!/?]|(?:^|[;\r\n])\s*(?:style|classDef|linkStyle|click|links?)\b/i
  return source.length <= 10_000 && plainDiagram.test(source.trimStart()) && !resourceOrConfig.test(source)
}

function getMermaid() {
  mermaidPromise ??= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      htmlLabels: false,
      maxTextSize: 10_000,
      maxEdges: 200,
      suppressErrorRendering: true,
    })
    return mermaid
  })
  return mermaidPromise
}

export default function AIInteractivePreview({ kind, source, isStreaming = false, theme = 'dark' }: {
  kind: PreviewKind
  source: string
  isStreaming?: boolean
  theme?: 'light' | 'dark'
}) {
  const isLight = theme === 'light'
  const statusClass = `px-3 py-5 text-sm ${isLight ? 'text-gray-600' : 'text-white/60'}`
  const [showSource, setShowSource] = React.useState(false)
  const [diagramResult, setDiagramResult] = React.useState<{
    source: string
    svg?: string
    error?: boolean
  } | null>(null)
  const sourceId = React.useId()
  const tooLarge = source.length > MAX_PREVIEW_LENGTH
  const unsupportedDiagram = kind === 'mermaid' && !isSupportedMermaidSource(source)

  React.useEffect(() => {
    if (kind !== 'mermaid' || isStreaming || tooLarge || unsupportedDiagram) return

    let cancelled = false
    getMermaid()
      .then((mermaid) => mermaid.render(`ai-diagram-${crypto.randomUUID()}`, source))
      .then(({ svg }) => {
        if (!cancelled) setDiagramResult({ source, svg })
      })
      .catch(() => {
        if (!cancelled) setDiagramResult({ source, error: true })
      })

    return () => { cancelled = true }
  }, [kind, source, isStreaming, tooLarge, unsupportedDiagram])

  const label = kind === 'html' ? 'Interactive example' : 'Diagram'
  const diagram = diagramResult?.source === source ? diagramResult.svg : undefined
  const diagramError = diagramResult?.source === source && diagramResult.error
  return (
    <div className={`my-3 overflow-hidden rounded-lg border ${isLight ? 'border-gray-200 bg-gray-50' : 'border-white/15 bg-white/5'} not-prose`}>
      <div className={`flex items-center justify-between gap-3 border-b ${isLight ? 'border-gray-200 text-gray-700' : 'border-white/10 text-white/70'} px-3 py-2 text-xs`}>
        <span className="font-medium">{label}</span>
        {!isStreaming && (
          <button
            type="button"
            aria-expanded={showSource}
            aria-controls={sourceId}
            onClick={() => setShowSource((shown) => !shown)}
            className={`rounded px-2 py-1 focus-visible:outline focus-visible:outline-2 ${isLight ? 'text-teal-700 hover:bg-teal-50 hover:text-teal-900 focus-visible:outline-teal-600' : 'text-purple-300 hover:bg-white/10 hover:text-purple-200 focus-visible:outline-purple-300'}`}
          >
            {showSource ? 'Hide source' : 'View source'}
          </button>
        )}
      </div>
      {isStreaming ? (
        <p role="status" className={statusClass}>Creating {label.toLowerCase()}…</p>
      ) : tooLarge ? (
        <p className={statusClass}>Preview is too large to render.</p>
      ) : unsupportedDiagram ? (
        <p className={statusClass}>This diagram uses unsupported features. View its source for details.</p>
      ) : kind === 'html' ? (
        <iframe
          title="AI interactive example"
          srcDoc={buildHtmlPreviewDocument(source)}
          sandbox="allow-scripts"
          allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'"
          referrerPolicy="no-referrer"
          className="block h-[420px] w-full bg-white"
        />
      ) : diagram ? (
        <iframe
          title="AI diagram"
          srcDoc={buildHtmlPreviewDocument(diagram, 'mermaid')}
          sandbox=""
          referrerPolicy="no-referrer"
          className="block h-80 w-full bg-white"
        />
      ) : (
        <p role="status" className={statusClass}>
          {diagramError ? 'Could not render this diagram. View its source for details.' : 'Rendering diagram…'}
        </p>
      )}
      {showSource && (
        <pre id={sourceId} className={`max-h-80 overflow-auto border-t ${isLight ? 'border-gray-200 bg-gray-50 text-gray-800' : 'border-white/10 bg-black/40 text-white/80'} p-3 text-xs`}><code>{source}</code></pre>
      )}
    </div>
  )
}
