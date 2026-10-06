export const LIBRARY_PAGE_SIZE = 24

/** Keep folders first while bounding the combined number of mounted cards. */
export function libraryPage<F, I>(folders: F[], items: I[], requestedPage: number) {
  const total = folders.length + items.length
  const pages = Math.max(1, Math.ceil(total / LIBRARY_PAGE_SIZE))
  const page = Math.max(0, Math.min(requestedPage, pages - 1))
  const start = page * LIBRARY_PAGE_SIZE
  const end = start + LIBRARY_PAGE_SIZE
  const itemOffset = Math.max(0, start - folders.length)
  return {
    folders: folders.slice(start, end),
    items: items.slice(itemOffset, Math.max(0, end - folders.length)),
    folderOffset: Math.min(start, folders.length),
    itemOffset,
    page,
    pages,
    total,
    from: total ? start + 1 : 0,
    to: Math.min(end, total),
  }
}

/** Drag indices are page-local; persist the complete list, including other pages. */
export function reorderLibraryPage<T>(items: T[], source: number, destination: number, offset: number) {
  const reordered = [...items]
  const [moved] = reordered.splice(offset + source, 1)
  reordered.splice(offset + destination, 0, moved)
  return reordered
}
