import { describe, expect, test } from 'bun:test'
import { parseApiDate } from '../lib/format'
import { fmtDuration } from '../components/Dashboard/Pages/Users/UserAnalytics/format'

describe('learning report timestamps', () => {
  test('naive backend datetimes represent UTC, including fractional seconds', () => {
    const previous = process.env.TZ
    try {
      process.env.TZ = 'Asia/Kolkata'
      expect(parseApiDate('2026-10-05 04:46:07.582645').toISOString()).toBe('2026-10-05T04:46:07.582Z')
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })
  test('explicit timezone offsets retain the same instant', () => {
    expect(parseApiDate('2026-10-05T10:16:07+05:30').toISOString()).toBe('2026-10-05T04:46:07.000Z')
  })
  test('date-only values retain their calendar day', () => {
    const previous = process.env.TZ
    try {
      process.env.TZ = 'America/Los_Angeles'
      const value = parseApiDate('2026-10-05')
      expect([value.getFullYear(), value.getMonth(), value.getDate()]).toEqual([2026, 9, 5])
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })
  test('invalid timestamps stay invalid for the display fallback', () => {
    expect(Number.isNaN(parseApiDate('invalid').getTime())).toBe(true)
  })
})

test('unavailable time tracking differs from a measured zero duration', () => {
  expect(fmtDuration(null)).toBe('—')
  expect(fmtDuration(undefined)).toBe('—')
  expect(fmtDuration(0)).toBe('0m')
  expect(fmtDuration(60)).toBe('1m')
})
