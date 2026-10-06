import { describe, expect, test } from 'bun:test'
import { libraryPage, LIBRARY_PAGE_SIZE, reorderLibraryPage } from '../lib/library/pagination.ts'

describe('Library pagination', () => {
  test('626 assets mount at most 24 cards and remain reachable exactly once', () => {
    const assets = Array.from({ length: 626 }, (_, i) => i)
    const first = libraryPage([], assets, 0)
    expect(first.items).toHaveLength(LIBRARY_PAGE_SIZE)
    expect(first.pages).toBe(27)
    const visited = Array.from({ length: first.pages }, (_, page) => {
      const result = libraryPage([], assets, page)
      expect(result.items.length + result.folders.length).toBeLessThanOrEqual(24)
      return result.items
    }).flat()
    expect(visited).toEqual(assets)
  })

  test('a page crossing from folders to items still contains only 24 cards', () => {
    const folders = Array.from({ length: 30 }, (_, i) => `folder-${i}`)
    const items = Array.from({ length: 40 }, (_, i) => `item-${i}`)
    const second = libraryPage(folders, items, 1)
    expect(second.folders).toEqual(folders.slice(24))
    expect(second.items).toEqual(items.slice(0, 18))
    expect(second.folderOffset).toBe(24)
    expect(second.itemOffset).toBe(0)
    expect(libraryPage(folders, items, 2).items).toEqual(items.slice(18))
  })

  test('removing the last item clamps a stale page to the remaining content', () => {
    const items = Array.from({ length: 24 }, (_, i) => i)
    expect(libraryPage([], items, 1)).toMatchObject({ page: 0, from: 1, to: 24, items })
    expect(libraryPage([], [], 5)).toMatchObject({ page: 0, pages: 1, from: 0, to: 0 })
  })

  test('dragging on a later page preserves all items outside that page', () => {
    const items = Array.from({ length: 70 }, (_, i) => i)
    const reordered = reorderLibraryPage(items, 0, 2, 24)
    expect(reordered.slice(0, 24)).toEqual(items.slice(0, 24))
    expect(reordered.slice(24, 27)).toEqual([25, 26, 24])
    expect(reordered.slice(27)).toEqual(items.slice(27))
    expect(items[24]).toBe(24)
    expect(reordered).toHaveLength(70)
  })
})
