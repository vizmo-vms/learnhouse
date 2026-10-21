import { describe, expect, test } from 'bun:test'
import { studyYouTubeOrigin } from '../lib/studyVideo'
import { ActiveStudyClock, formatStudyTime } from '../lib/studyTime'

describe('active learning time', () => {
  test('visible reading stops at five idle minutes and resumes without backfill', () => {
    const clock = new ActiveStudyClock(0, true)
    expect(clock.read(360000)).toBe(300000)
    clock.interact(400000)
    expect(clock.read(415000)).toBe(315000)
  })
  test('hiding immediately pauses, even during playback', () => {
    const clock = new ActiveStudyClock(0, true)
    clock.setPlaying(0, true)
    clock.setVisible(10000, false)
    expect(clock.read(600000)).toBe(10000)
    clock.setVisible(600000, true)
    expect(clock.read(615000)).toBe(25000)
  })
  test('visible video playback counts beyond the interaction cutoff', () => {
    const clock = new ActiveStudyClock(0, true)
    clock.setPlaying(0, true)
    expect(clock.read(600000)).toBe(600000)
    clock.setPlaying(600000, false)
    expect(clock.read(900000)).toBe(600000)
  })
  test('scroll or input extends the reading window without resetting the total', () => {
    const clock = new ActiveStudyClock(0, true)
    clock.interact(240000)
    expect(clock.read(600000)).toBe(540000)
  })
  test('backward clock samples cannot subtract or double-count time', () => {
    const clock = new ActiveStudyClock(0, true)
    expect(clock.read(15000)).toBe(15000)
    expect(clock.read(10000)).toBe(15000)
    expect(clock.read(20000)).toBe(20000)
  })
})

test('duration labels distinguish unavailable data from a measured zero', () => {
  expect(formatStudyTime(null)).toBe('Not tracked')
  expect(formatStudyTime(0)).toBe('0s')
  expect(formatStudyTime(75)).toBe('1m 15s')
  expect(formatStudyTime(3690)).toBe('1h 1m')
})


test('playback observation accepts only HTTPS YouTube embed hosts', () => {
  expect(studyYouTubeOrigin('https://www.youtube.com/embed/abc?enablejsapi=1')?.hostname).toBe('www.youtube.com')
  expect(studyYouTubeOrigin('https://www.youtube-nocookie.com/embed/abc')?.hostname).toBe('www.youtube-nocookie.com')
  for (const url of ['https://www.youtube.com.evil.test/embed/abc', 'http://www.youtube.com/embed/abc', 'https://www.youtube.com/watch?v=abc', 'javascript:alert(1)', 'https://evil.test/embed/abc']) {
    expect(studyYouTubeOrigin(url)).toBeNull()
  }
})
