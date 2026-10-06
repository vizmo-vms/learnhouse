'use client'

import React from 'react'
import { useTranslation } from 'react-i18next'

type Props = {
  page: number
  pages: number
  total: number
  from: number
  to: number
  onPageChange: (_page: number) => void
}

export default function LibraryPagination({ page, pages, total, from, to, onPageChange }: Props) {
  const { t } = useTranslation()
  if (pages <= 1) return null
  const buttonClass = 'rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-40 disabled:cursor-not-allowed'
  return (
    <nav aria-label={t('library.pagination.label', { defaultValue: 'Library pages' })} className="flex flex-wrap items-center justify-between gap-3">
      <span role="status" className="text-sm text-gray-500">
        {t('library.pagination.range', { defaultValue: '{{from}}–{{to}} of {{total}} items', from, to, total })}
      </span>
      <div className="flex items-center gap-2">
        <button type="button" disabled={page === 0} onClick={() => onPageChange(page - 1)} className={buttonClass}>
          {t('library.pagination.previous', { defaultValue: 'Previous' })}
        </button>
        <span className="text-sm text-gray-500">
          {t('library.pagination.page', { defaultValue: 'Page {{page}} of {{pages}}', page: page + 1, pages })}
        </span>
        <button type="button" disabled={page === pages - 1} onClick={() => onPageChange(page + 1)} className={buttonClass}>
          {t('library.pagination.next', { defaultValue: 'Next' })}
        </button>
      </div>
    </nav>
  )
}
