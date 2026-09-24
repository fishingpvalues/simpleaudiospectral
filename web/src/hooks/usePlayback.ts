import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import type { View } from "@/lib/scale"

/** Delay before retrying play() once the transcoded source is set. */
const RETRY_MS = 50

/** The <audio> element of the open file. The browser plays what it can; on a
 * decode error the source switches once to a FLAC transcode from the server. */
export function usePlayback(path: string | null) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  // The Viewer needs the element as a prop; a ref's .current cannot be read during render.
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [transcode, setTranscode] = useState(false)
  const [playError, setPlayError] = useState<string | null>(null)

  useEffect(() => {
    if (!path) return
    setTranscode(false)
    setPlayError(null)
  }, [path])

  /** Plays from the view start when the playhead is outside the view. */
  const togglePlay = useCallback((view: View) => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) {
      if (a.currentTime < view.t0 || a.currentTime > view.t1) a.currentTime = view.t0
      a.play().catch(() => {}) // an unplayable source is handled by onError
    } else a.pause()
  }, [])

  /** Moves the playhead; false when there is no audio element to move. */
  const seek = useCallback((t: number) => {
    if (!audioRef.current) return false
    audioRef.current.currentTime = t
    return true
  }, [])

  const bind = useCallback((el: HTMLAudioElement | null) => {
    audioRef.current = el
    setAudioEl(el)
  }, [])

  const audioProps = {
    ref: bind,
    src: path ? api.audioUrl(path, transcode) : undefined,
    preload: "none" as const,
    onError: () => {
      if (!transcode) {
        setTranscode(true)
        setTimeout(() => void audioRef.current?.play().catch(() => {}), RETRY_MS)
      } else {
        setPlaying(false)
        setPlayError("Playback failed: the browser cannot play this file and the server could not transcode it.")
      }
    },
    onPlay: () => {
      setPlayError(null)
      setPlaying(true)
    },
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
  }

  return { audioEl, playing, setPlaying, playError, togglePlay, seek, audioProps }
}
