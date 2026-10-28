// Read-only extraction: no scripts from the supplied HTML are executed.
// Usage: node scripts/capture-design.mjs <export.html> [output-directory]
import { readFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { gunzipSync } from 'node:zlib'
import { chromium } from '@playwright/test'

const input = process.argv[2]
if (!input) throw new Error('Pass the local Claude Design HTML export path')
const output = resolve(process.argv[3] ?? 'test-results/design-reference')
await mkdir(output, { recursive: true })
const island = (html, name) => {
  const match = html.match(new RegExp(`<script type="__bundler/${name}"[^>]*>([\\s\\S]*?)</script>`))
  if (!match) throw new Error(`Missing ${name} in design export`)
  return JSON.parse(match[1])
}
const source = await readFile(input, 'utf8')
const manifest = island(source, 'manifest')
const board = island(source, 'template')
const frames = [...board.matchAll(/<iframe src="about:blank#([^"]+)" title="([^"]+)" width="(\d+)" height="(\d+)"/g)]
const font = await readFile(new URL('../public/fonts/PretendardVariable.woff2', import.meta.url))
const browser = await chromium.launch()
try {
  for (const [, key, title, width, height] of frames) {
    const entry = manifest[key]
    const bytes = Buffer.from(entry.data, 'base64')
    const bundle = (entry.compressed ? gunzipSync(bytes) : bytes).toString('utf8')
    const template = island(bundle, 'template')
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/sc-camel-view-box/g, 'viewBox').replace(/sc-raw-(select|table|thead|tbody|tfoot|tr|th|td|caption)/g, '$1')
    const page = await browser.newPage({ viewport: { width: Number(width), height: Number(height) } })
    await page.route('**/*', (route) => {
      if (route.request().url() === 'http://design.local/') return route.fulfill({ contentType: 'text/html', body: template })
      if (route.request().url().endsWith('/fonts/PretendardVariable.woff2')) return route.fulfill({ contentType: 'font/woff2', body: font })
      return route.abort()
    })
    await page.goto('http://design.local/')
    await page.evaluate(() => document.fonts.ready)
    const id = title.split(' ')[0]
    await page.screenshot({ path: join(output, `${id}.png`), fullPage: true })
    await page.close()
  }
  console.log(`Captured ${frames.length} reference frames in ${output}`)
} finally {
  await browser.close()
}
