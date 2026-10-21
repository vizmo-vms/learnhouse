/** Observe supported YouTube embeds through Google's player API. */
type Player = { getPlayerState(): number }
type YouTubeAPI = { Player: new (_frame: HTMLIFrameElement, _options: object) => Player }
type PlayerWindow = Window & { YT?: YouTubeAPI; onYouTubeIframeAPIReady?: () => void }
let apiReady: Promise<YouTubeAPI> | undefined

function youtubeAPI() {
  const host = window as PlayerWindow
  if (host.YT?.Player) return Promise.resolve(host.YT)
  apiReady ??= new Promise((resolve) => {
    const previous = host.onYouTubeIframeAPIReady
    host.onYouTubeIframeAPIReady = () => {
      previous?.()
      if (host.YT) resolve(host.YT)
    }
    if (!document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
      const script = document.createElement('script')
      script.src = 'https://www.youtube.com/iframe_api'
      document.head.appendChild(script)
    }
  })
  return apiReady
}

export function studyYouTubeOrigin(source: string) {
  try {
    const url = new URL(source)
    return url.protocol === 'https:' && ['www.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)
      && url.pathname.startsWith('/embed/') ? url : null
  } catch { return null }
}

export function observeStudyYouTube() {
  const players = new Map<HTMLIFrameElement, Player | null>()
  let disposed = false
  return {
    playing: () => {
      for (const frame of document.querySelectorAll('iframe')) {
        if (players.has(frame) || frame.closest('[data-study-video-playing]')) continue
        const url = studyYouTubeOrigin(frame.src)
        if (!url) continue
        players.set(frame, null)
        // Enable the API before the player is first used. Only recognized
        // YouTube embeds are eligible; arbitrary iframe messages are ignored.
        if (url.searchParams.get('enablejsapi') !== '1') {
          url.searchParams.set('enablejsapi', '1')
          url.searchParams.set('origin', window.location.origin)
          frame.src = url.toString()
        }
        void youtubeAPI().then((api) => {
          if (!disposed && frame.isConnected) players.set(frame, new api.Player(frame, {}))
        }).catch(() => { /* Reading still uses the ordinary idle cutoff. */ })
      }
      return Array.from(players).filter(([frame, player]) => {
        if (!frame.isConnected) { players.delete(frame); return false }
        try { return player?.getPlayerState() === 1 } catch { return false }
      }).map(([frame]) => frame)
    },
    dispose: () => { disposed = true; players.clear() },
  }
}
