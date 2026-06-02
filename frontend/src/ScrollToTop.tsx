import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Restores the main scroll container to the top whenever the route changes.
 * Without this, switching from a long Dashboard to Settings keeps the prior
 * scroll offset, which makes the new page feel broken on first load.
 */
export default function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    const main = document.querySelector('.main') as HTMLElement | null
    if (main) main.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}
