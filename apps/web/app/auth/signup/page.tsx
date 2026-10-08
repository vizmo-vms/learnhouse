import { redirect } from 'next/navigation'

export default async function SignUp({ searchParams }: {
  searchParams: Promise<{ inviteCode?: string }>
}) {
  const { inviteCode } = await searchParams
  const query = inviteCode ? `?${new URLSearchParams({ inviteCode })}` : ''
  redirect(`/login${query}`)
}
