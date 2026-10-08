import { expect, test } from 'bun:test'
import SignUp from '../app/auth/signup/page'

async function redirectedTo(params) {
  try {
    await SignUp({ searchParams: Promise.resolve(params) })
  } catch (error) {
    if (error.digest?.startsWith('NEXT_REDIRECT;')) return error.digest.split(';')[2]
    throw error
  }
  throw new Error('Signup did not redirect')
}

test('invitation survives the hidden-signup redirect to Google login', async () => {
  expect(await redirectedTo({ inviteCode: '1Whz4pT5' })).toBe('/login?inviteCode=1Whz4pT5')
})

test('ordinary public signup stays hidden', async () => {
  expect(await redirectedTo({})).toBe('/login')
})

test('untrusted invite input cannot add a next URL or an external redirect', async () => {
  const url = new URL(await redirectedTo({ inviteCode: 'X&next=https://evil.example' }), 'https://learn.vizmo.app')
  expect(url.pathname).toBe('/login')
  expect(url.searchParams.get('inviteCode')).toBe('X&next=https://evil.example')
  expect(url.searchParams.has('next')).toBe(false)
})
