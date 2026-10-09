import assert from 'node:assert/strict'
import test from 'node:test'
import { QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../lib/query/keys.ts'

test('management list fetches independently after a fresh learner list', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  await client.fetchQuery({
    queryKey: queryKeys.courses.list('vizmo'),
    queryFn: () => ['basic-course'],
  })
  const management = await client.fetchQuery({
    queryKey: queryKeys.courses.managementList('vizmo'),
    queryFn: () => ['basic-course', 'sales-course', 'draft-course'],
  })
  assert.deepEqual(management, ['basic-course', 'sales-course', 'draft-course'])
  assert.deepEqual(client.getQueryData(queryKeys.courses.list('vizmo')), ['basic-course'])
  await client.invalidateQueries({ queryKey: queryKeys.courses.list('vizmo') })
  assert.equal(client.getQueryState(queryKeys.courses.managementList('vizmo')).isInvalidated, true)
  client.clear()
})
