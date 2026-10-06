'use client'

import React, { useId, useState } from 'react'
import Link from 'next/link'
import { useAnalyticsDbQuery } from './useAnalyticsDashboard'
import { parseApiDate } from '@lib/format'

type ProgressRow = {
  user_id: number
  first_name: string
  last_name: string
  username: string
  email: string
  trailrun_id: number | null
  course_uuid: string | null
  course_name: string | null
  status: string
  activities_completed: number
  activities_total: number
  progress_pct: number
  enrolled_at: string | null
  last_activity_at: string | null
}

type ProgressReport = {
  data: ProgressRow[]
  total: number
  summary: { learners: number; enrollments: number; completions: number; average_progress: number }
}

const statusLabels: Record<string, string> = {
  NOT_ENROLLED: 'Not enrolled',
  STATUS_IN_PROGRESS: 'In progress',
  STATUS_COMPLETED: 'Completed',
  STATUS_PAUSED: 'Paused',
  STATUS_CANCELLED: 'Cancelled',
}

function date(value: string | null, includeTime = false) {
  if (!value) return '—'
  const parsed = parseApiDate(value)
  return Number.isNaN(parsed.getTime()) ? '—' : includeTime ? parsed.toLocaleString() : parsed.toLocaleDateString()
}

export default function LearnerProgressTable({ courseUUID }: { courseUUID?: string }) {
  const id = useId()
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const perPage = 25
  const params: Record<string, string> = { search, page: String(page), per_page: String(perPage) }
  if (status) params.status = status
  if (courseUUID) params.course_uuid = courseUUID
  const { data, isPending, isError, isFetching, refetch } = useAnalyticsDbQuery('learner_progress', params, 60_000)
  const report = data as ProgressReport | undefined
  const pages = Math.max(1, Math.ceil((report?.total || 0) / perPage))

  return (
    <section className="bg-white rounded-xl nice-shadow p-5 min-w-0" aria-labelledby={`${id}-heading`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={`${id}-heading`} className="text-base font-semibold text-gray-900">Employee course progress</h2>
          <p className="mt-1 text-sm text-gray-500">See who has enrolled, what they have completed and who has yet to start.</p>
        </div>
        <button type="button" disabled={isFetching} onClick={() => refetch()}
          className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50">
          {isFetching && !isPending ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <form className="mt-5 flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault(); setSearch(searchInput.trim()); setPage(1)
      }}>
        <div className="flex-1 min-w-48">
          <label htmlFor={`${id}-search`} className="block mb-1 text-xs font-medium text-gray-600">Search employees{!courseUUID && ' or courses'}</label>
          <input id={`${id}-search`} type="search" value={searchInput} maxLength={100}
            onChange={(event) => setSearchInput(event.target.value)} placeholder="Name, email or course"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label htmlFor={`${id}-status`} className="block mb-1 text-xs font-medium text-gray-600">Status</label>
          <select id={`${id}-status`} value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }}
            className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <button type="submit" className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700">Search</button>
      </form>

      {isPending ? (
        <p className="py-12 text-center text-sm text-gray-500" role="status">Loading employee progress…</p>
      ) : isError || !report ? (
        <p className="py-12 text-center text-sm text-red-700" role="alert">Could not load employee progress. Use Refresh to try again.</p>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-sm text-gray-600" aria-live="polite">
            <span><strong className="text-gray-900">{report.summary.learners}</strong> employees</span>
            <span><strong className="text-gray-900">{report.summary.enrollments}</strong> enrollments</span>
            <span><strong className="text-gray-900">{report.summary.completions}</strong> completed courses</span>
            <span><strong className="text-gray-900">{report.summary.average_progress}%</strong> average progress</span>
          </div>
          {report.data.length === 0 ? (
            <p className="py-12 text-center text-sm text-gray-500">No employees match these filters.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Employee enrollments and progress{courseUUID ? ' for this course' : ' across courses'}</caption>
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                    {['Employee', 'Course', 'Status', 'Progress', 'Enrolled', 'Last activity'].map((heading) => (
                      <th key={heading} scope="col" className="pb-3 pr-4 font-medium whitespace-nowrap">{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.data.map((row) => {
                    const label = statusLabels[row.status] || row.status
                    const name = [row.first_name, row.last_name].filter(Boolean).join(' ') || row.username
                    return (
                      <tr key={`${row.user_id}-${row.trailrun_id || 'none'}`} className="border-b border-gray-100 last:border-0">
                        <td className="py-4 pr-4 min-w-44">
                          <Link href={`/dash/users/analytics/${row.user_id}`} className="font-medium text-gray-900 hover:underline">{name}</Link>
                          <div className="mt-1 text-xs text-gray-500">{row.email}</div>
                        </td>
                        <td className="py-4 pr-4 min-w-48 max-w-80">
                          {row.course_uuid ? <Link className="text-gray-700 hover:underline" href={`/dash/courses/course/${row.course_uuid.replace('course_', '')}/analytics`}>{row.course_name}</Link> : <span className="text-gray-500">{courseUUID ? 'This course' : 'No course enrollments'}</span>}
                        </td>
                        <td className="py-4 pr-4 whitespace-nowrap"><span className={`inline-block rounded-full px-2 py-1 text-xs ${row.status === 'STATUS_COMPLETED' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600'}`}>{label}</span></td>
                        <td className="py-4 pr-4 min-w-36">
                          {row.trailrun_id ? <>
                            <div className="flex justify-between gap-3 text-xs"><span>{row.activities_completed} / {row.activities_total} lessons</span><strong>{row.progress_pct}%</strong></div>
                            <progress aria-label={`${name}: ${row.course_name} progress`} value={row.progress_pct} max={100} className="mt-2 h-1.5 w-full accent-blue-600" />
                          </> : <span className="text-gray-400">—</span>}
                        </td>
                        <td className="py-4 pr-4 whitespace-nowrap text-xs text-gray-500">{date(row.enrolled_at)}</td>
                        <td className="py-4 whitespace-nowrap text-xs text-gray-500">{date(row.last_activity_at, true)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-gray-500">
            <span>{report.total} records · All time</span>
            <div className="flex items-center gap-3">
              <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-md border px-3 py-1.5 disabled:opacity-40">Previous</button>
              <span>Page {page} of {pages}</span>
              <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-md border px-3 py-1.5 disabled:opacity-40">Next</button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
