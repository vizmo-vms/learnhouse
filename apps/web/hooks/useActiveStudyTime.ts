'use client'

import { useEffect } from 'react'
import { observeStudyYouTube, studyYouTubeOrigin } from '@lib/studyVideo'
import { ActiveStudyClock } from '@lib/studyTime'
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader, secureFetch } from '@services/utils/ts/requests'

function inViewport(element: Element) {
  const rect = element.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
    && rect.top < window.innerHeight && rect.left < window.innerWidth
}

/** Best-effort learning estimate. Only counters leave the browser. */
export function useActiveStudyTime(activityUUID: string | undefined, enabled: boolean, token?: string) {
  useEffect(() => {
    if (!activityUUID || !enabled) return
    const clock = new ActiveStudyClock(performance.now(), !document.hidden)
    const sessionID = crypto.randomUUID()
    const youtube = observeStudyYouTube()
    let stopped = false
    let lastSent = -1
    const send = (force = false, handshake = false) => {
      if (stopped) return
      const total = handshake ? 0 : clock.read(performance.now())
      if (!force && total === lastSent) return
      lastSent = total
      const partial = Array.from(document.querySelectorAll('iframe')).some((frame) =>
        !frame.closest('[data-study-video-playing]') && !studyYouTubeOrigin(frame.src))
      void secureFetch(`${getAPIUrl()}activities/${activityUUID}/study-time`, {
        ...RequestBodyWithAuthHeader('POST', { session_id: sessionID, total_ms: total, partial }, null, token),
        keepalive: true,
      }).then(async (response) => {
        if (response.ok && (await response.json()).tracking === false) stopped = true
        if (response.status === 401 || response.status === 403 || response.status === 404) stopped = true
      }).catch(() => { /* A network failure must not interrupt the lesson. */ })
    }
    const playback = () => {
      const playing = Array.from(document.querySelectorAll('video')).some((video) =>
        !video.paused && !video.ended && video.readyState >= 3 && inViewport(video))
        || Array.from(document.querySelectorAll('[data-study-video-playing="true"]')).some(inViewport)
        || youtube.playing().some(inViewport)
      clock.setPlaying(performance.now(), playing)
    }
    const interact = () => { clock.interact(performance.now()); playback() }
    const visibility = () => {
      clock.setVisible(performance.now(), !document.hidden)
      playback()
      send(true)
    }
    const pagehide = () => {
      clock.setVisible(performance.now(), false)
      send(true)
    }
    const pageshow = () => { clock.setVisible(performance.now(), !document.hidden); playback() }
    const inputEvents = ['pointerdown', 'keydown', 'scroll', 'touchstart'] as const
    const videoEvents = ['play', 'playing', 'pause', 'ended', 'waiting'] as const
    inputEvents.forEach((event) => document.addEventListener(event, interact, { capture: true, passive: true }))
    videoEvents.forEach((event) => document.addEventListener(event, playback, true))
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('pagehide', pagehide)
    window.addEventListener('pageshow', pageshow)
    playback()
    send(true, true)
    const heartbeat = window.setInterval(() => send(), 15_000)
    const videoPoll = window.setInterval(playback, 1_000)
    return () => {
      youtube.dispose()
      window.clearInterval(heartbeat)
      window.clearInterval(videoPoll)
      inputEvents.forEach((event) => document.removeEventListener(event, interact, true))
      videoEvents.forEach((event) => document.removeEventListener(event, playback, true))
      document.removeEventListener('visibilitychange', visibility)
      window.removeEventListener('pagehide', pagehide)
      window.removeEventListener('pageshow', pageshow)
      send(true)
      stopped = true
    }
  }, [activityUUID, enabled, token])
}
