/**
 * ScrollContainerContext — exposes the app shell's scrolling `<main>` element.
 *
 * Held in state (set via callback ref) so consumers re-render once the element
 * exists; null until the first commit. Virtualized lists use it as their
 * `customScrollParent`, since the window itself never scrolls.
 */

import { createContext, useContext } from 'react'

export const ScrollContainerContext = createContext<HTMLElement | null>(null)

export function useScrollContainer(): HTMLElement | null {
  return useContext(ScrollContainerContext)
}
