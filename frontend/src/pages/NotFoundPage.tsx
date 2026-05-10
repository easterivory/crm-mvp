import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 p-6 text-center">
      <h1 className="text-4xl font-semibold text-zinc-100">404</h1>
      <p className="text-sm text-zinc-500">Page not found</p>
      <Link to="/" className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400">
        Back to app
      </Link>
    </div>
  )
}
