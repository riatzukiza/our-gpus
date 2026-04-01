import { createReadStream, existsSync } from 'node:fs'
import { stat } from 'node:fs/promises'
import { Readable } from 'node:stream'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'

const PORT = Number.parseInt(process.env.PORT || '5173', 10)
const API_ORIGIN = process.env.API_ORIGIN || 'http://api:8000'
const DIST_DIR = join(process.cwd(), 'dist')
const INDEX_PATH = join(DIST_DIR, 'index.html')

const MIME_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

const sendFile = async (res, filePath, cacheControl) => {
  const fileStat = await stat(filePath)
  const extension = extname(filePath)

  res.writeHead(200, {
    'Cache-Control': cacheControl,
    'Content-Length': fileStat.size,
    'Content-Type': MIME_TYPES[extension] || 'application/octet-stream',
  })

  createReadStream(filePath).pipe(res)
}

const shouldProxy = (pathname) => pathname.startsWith('/api/') || pathname === '/metrics'

const proxyRequest = async (req, res, url) => {
  const requestBody = req.method === 'GET' || req.method === 'HEAD'
    ? undefined
    : await new Response(Readable.toWeb(req)).arrayBuffer()

  const upstreamUrl = new URL(url.pathname + url.search, API_ORIGIN)
  const upstreamResponse = await fetch(upstreamUrl, {
    method: req.method,
    headers: req.headers,
    body: requestBody,
    duplex: requestBody ? 'half' : undefined,
  })

  const headers = {}
  upstreamResponse.headers.forEach((value, key) => {
    headers[key] = value
  })
  res.writeHead(upstreamResponse.status, headers)

  if (!upstreamResponse.body) {
    res.end()
    return
  }

  Readable.fromWeb(upstreamResponse.body).pipe(res)
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url || '/', 'http://localhost')
    const pathname = decodeURIComponent(url.pathname)

    if (shouldProxy(pathname)) {
      await proxyRequest(req, res, url)
      return
    }

    const requestedPath = normalize(join(DIST_DIR, pathname))
    const insideDist = requestedPath.startsWith(DIST_DIR)

    if (insideDist && existsSync(requestedPath) && (await stat(requestedPath)).isFile()) {
      const cacheControl = pathname.startsWith('/assets/')
        ? 'public, max-age=31536000, immutable'
        : 'no-store'
      await sendFile(res, requestedPath, cacheControl)
      return
    }

    await sendFile(res, INDEX_PATH, 'no-store')
  } catch (error) {
    res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' })
    res.end(`static-server-error: ${error instanceof Error ? error.message : 'unknown error'}`)
  }
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`our-gpus-web listening on http://0.0.0.0:${PORT}`)
})
