import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const directory = await mkdtemp(join(tmpdir(), 'crm-funnel-controls-'))
try {
  const outfile = join(directory, 'tests.cjs')
  await build({ entryPoints: [fileURLToPath(new URL('./funnel-controls.test.tsx', import.meta.url))],
    outfile, bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic' })
  const result = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' })
  process.exitCode = result.status ?? 1
} finally {
  await rm(directory, { recursive: true, force: true })
}
