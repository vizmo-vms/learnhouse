'use client'

import React from 'react'
import Link from 'next/link'
import {
  BookOpen,
  CheckCircle,
  ListChecks,
  Path,
  UsersThree,
} from '@phosphor-icons/react'
import { useAnalyticsDbQuery } from './useAnalyticsDashboard'
import LearnerProgressTable from './LearnerProgressTable'

type Summary = {
  learners: number
  courses: number
  enrollments: number
  completions: number
  completed_activities: number
  completion_rate: number
}

type CourseRow = {
  course_uuid: string
  name: string
  published: boolean
  enrollments: number
  completions: number
  activities: number
  average_progress: number
}

type EnrollmentRow = {
  enrolled_at: string
  status: string
  course_uuid: string
  course_name: string
  learner_name: string
}

type Overview = {
  summary: Summary
  courses: CourseRow[]
  recent_enrollments: EnrollmentRow[]
}

const number = (value: unknown) => Number(value || 0).toLocaleString()

export default function PostgresOverview() {
  const { data, isLoading, isError } = useAnalyticsDbQuery('basic_overview')
  const overview = data as Overview | undefined

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-[1600px] mx-auto" aria-busy="true" aria-label="Loading analytics">
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="h-28 rounded-xl bg-gray-100 animate-pulse" />
          ))}
        </div>
        <div className="h-72 rounded-xl bg-gray-100 animate-pulse" />
      </div>
    )
  }

  if (isError || !overview) {
    return (
      <div role="alert" className="max-w-xl mx-auto bg-white rounded-xl nice-shadow p-8 text-center">
        <h2 className="font-semibold text-gray-800">Could not load analytics</h2>
        <p className="mt-2 text-sm text-gray-500">Refresh the page to try again.</p>
      </div>
    )
  }

  const stats = [
    { label: 'Learners', value: overview.summary.learners, icon: UsersThree },
    { label: 'Courses', value: overview.summary.courses, icon: BookOpen },
    { label: 'Enrollments', value: overview.summary.enrollments, icon: Path },
    { label: 'Completions', value: overview.summary.completions, icon: CheckCircle },
    { label: 'Activities completed', value: overview.summary.completed_activities, icon: ListChecks },
  ]

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto w-full">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {stats.map(({ label, value, icon: Icon }) => (
          <div key={label} className="bg-white rounded-xl nice-shadow p-4 min-w-0">
            <div className="flex items-center justify-between gap-2 text-gray-400">
              <span className="text-xs font-medium uppercase tracking-wide truncate">{label}</span>
              <Icon size={18} weight="duotone" aria-hidden="true" />
            </div>
            <div className="mt-3 text-3xl font-bold tracking-tight text-gray-900">{number(value)}</div>
            {label === 'Completions' && (
              <p className="mt-1 text-xs text-gray-400">{number(overview.summary.completion_rate)}% of enrollments</p>
            )}
          </div>
        ))}
      </div>

      <LearnerProgressTable />

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)] gap-6">
        <section className="bg-white rounded-xl nice-shadow p-5 min-w-0" aria-labelledby="course-performance-heading">
          <h2 id="course-performance-heading" className="text-sm font-semibold text-gray-700">Course performance</h2>
          {overview.courses.length === 0 ? (
            <p className="py-16 text-center text-sm text-gray-400">No courses yet</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                    <th className="pb-3 font-medium">Course</th>
                    <th className="pb-3 font-medium text-right">Enrollments</th>
                    <th className="pb-3 font-medium text-right">Completions</th>
                    <th className="pb-3 font-medium text-right">Avg. progress</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.courses.map((course) => (
                    <tr key={course.course_uuid} className="border-b border-gray-50 last:border-0">
                      <td className="py-3 pr-4">
                        <Link className="font-medium text-gray-800 hover:underline" href={`/dash/courses/course/${course.course_uuid.replace('course_', '')}/analytics`}>{course.name}</Link>
                        <div className="text-xs text-gray-400">{course.activities} activities · {course.published ? 'Published' : 'Draft'}</div>
                      </td>
                      <td className="py-3 text-right text-gray-600">{number(course.enrollments)}</td>
                      <td className="py-3 text-right text-gray-600">{number(course.completions)}</td>
                      <td className="py-3 text-right font-medium text-gray-700">{number(course.average_progress)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="bg-white rounded-xl nice-shadow p-5 min-w-0" aria-labelledby="recent-enrollments-heading">
          <h2 id="recent-enrollments-heading" className="text-sm font-semibold text-gray-700">Recent enrollments</h2>
          {overview.recent_enrollments.length === 0 ? (
            <p className="py-16 text-center text-sm text-gray-400">No enrollments yet</p>
          ) : (
            <ul className="mt-3 divide-y divide-gray-100">
              {overview.recent_enrollments.map((row, index) => (
                <li key={`${row.course_uuid}-${row.enrolled_at}-${index}`} className="py-3 first:pt-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{row.learner_name}</p>
                      <p className="text-xs text-gray-500 truncate">{row.course_name}</p>
                    </div>
                    <time className="text-xs text-gray-400 whitespace-nowrap" dateTime={row.enrolled_at}>
                      {new Date(row.enrolled_at).toLocaleDateString()}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
