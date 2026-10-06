'use client'
import React from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import AIInteractivePreview from './AIInteractivePreview'

type AIMarkdownRendererProps = {
  content: string
  isStreaming?: boolean
  theme?: 'light' | 'dark'
}

function textFromChildren(children: React.ReactNode): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(textFromChildren).join('')
  if (React.isValidElement<{ children?: React.ReactNode }>(children)) {
    return textFromChildren(children.props.children)
  }
  return ''
}

function AIMarkdownRenderer({ content, isStreaming = false, theme = 'dark' }: AIMarkdownRendererProps) {
  const isLight = theme === 'light'
  const headingColor = isLight ? 'text-gray-900' : 'text-white/90'
  const textColor = isLight ? 'text-gray-700' : 'text-white/80'
  const borderColor = isLight ? 'border-gray-200' : 'border-white/20'
  const components = React.useMemo<Components>(() => ({
    // Headings
    h1: ({ children }) => (
      <h1 className={`text-lg font-bold ${headingColor} mt-4 mb-2 first:mt-0`}>{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className={`text-base font-bold ${headingColor} mt-3 mb-2 first:mt-0`}>{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className={`text-sm font-bold ${headingColor} mt-2 mb-1 first:mt-0`}>{children}</h3>
    ),
    // Paragraph
    p: ({ children }) => (
      <p className={`${textColor} text-sm leading-relaxed mb-2 last:mb-0`}>{children}</p>
    ),
    // Bold and italic
    strong: ({ children }) => (
      <strong className={`font-semibold ${headingColor}`}>{children}</strong>
    ),
    em: ({ children }) => (
      <em className={`italic ${textColor}`}>{children}</em>
    ),
    // Lists
    ul: ({ children }) => (
      <ul className={`list-disc list-inside ${textColor} text-sm mb-2 space-y-1 ms-2`}>
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className={`list-decimal list-inside ${textColor} text-sm mb-2 space-y-1 ms-2`}>
        {children}
      </ol>
    ),
    li: ({ children }) => (
      <li className={textColor}>{children}</li>
    ),
    // Code blocks
    code: ({ className, children, ...props }) => {
      const isInline = !className
      if (isInline) {
        return (
          <code
            className={`${isLight ? 'bg-gray-100 text-teal-800' : 'bg-white/10 text-purple-300'} px-1.5 py-0.5 rounded text-xs font-mono`}
            {...props}
          >
            {children}
          </code>
        )
      }
      return (
        <code
          className={`${className} block ${isLight ? 'bg-gray-50 text-gray-800' : 'bg-black/40'} rounded-lg p-3 text-xs font-mono overflow-x-auto my-2`}
          {...props}
        >
          {children}
        </code>
      )
    },
    pre: ({ children }) => {
      const code = React.isValidElement<{ className?: string; children?: React.ReactNode }>(children)
        ? children
        : null
      const kind = code?.props.className?.match(/\blanguage-(html|mermaid)\b/)?.[1]
      if (kind === 'html' || kind === 'mermaid') {
        return (
          <AIInteractivePreview
            kind={kind}
            source={textFromChildren(code?.props.children).trimEnd()}
            isStreaming={isStreaming}
            theme={theme}
          />
        )
      }
      return <pre className={`${isLight ? 'bg-gray-50 text-gray-800' : 'bg-black/40'} rounded-lg overflow-x-auto my-2`}>{children}</pre>
    },
    // Blockquote
    blockquote: ({ children }) => (
      <blockquote className={`border-s-2 ${isLight ? 'border-teal-600 text-gray-600' : 'border-purple-500/50 text-white/70'} ps-3 my-2 italic`}>
        {children}
      </blockquote>
    ),
    // Links
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={`${isLight ? 'text-teal-700 hover:text-teal-900' : 'text-purple-400 hover:text-purple-300'} underline`}
      >
        {children}
      </a>
    ),
    // Horizontal rule
    hr: () => <hr className={`${isLight ? 'border-gray-200' : 'border-white/10'} my-3`} />,
    // Table
    table: ({ children }) => (
      <div className="overflow-x-auto my-2">
        <table className="min-w-full text-xs border-collapse">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className={isLight ? 'bg-gray-100' : 'bg-white/10'}>{children}</thead>
    ),
    th: ({ children }) => (
      <th className={`border ${borderColor} px-2 py-1 text-start ${headingColor} font-semibold`}>
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className={`border ${borderColor} px-2 py-1 ${textColor}`}>
        {children}
      </td>
    ),
  }), [isStreaming, theme, isLight, headingColor, textColor, borderColor])
  return (
    <div data-ai-theme={theme} className={`ai-markdown-content prose ${isLight ? 'text-gray-700' : 'prose-invert'} prose-sm max-w-none`}>
      <style jsx global>{`
        @keyframes cursor-blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .streaming-cursor {
          animation: cursor-blink 0.8s ease-in-out infinite;
        }
      `}</style>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
      {isStreaming && (
        <span className={`streaming-cursor inline-block w-1.5 h-4 ${isLight ? 'bg-teal-600' : 'bg-purple-400/90'} ms-0.5 align-middle rounded-sm`} />
      )}
    </div>
  )
}

export default AIMarkdownRenderer
