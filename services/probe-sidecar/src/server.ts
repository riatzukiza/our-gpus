import express, { type Request, type Response } from 'express'
import { ProxyAgent, setGlobalDispatcher } from 'undici'

interface HostInput {
  hostId: number
  ip: string
  port: number
}

interface ProbeBatchRequest {
  hosts: HostInput[]
  timeoutSeconds?: number
  retries?: number
  concurrency?: number
}

interface ProbeBatchResult {
  hostId: number
  status: 'success' | 'timeout' | 'error' | 'non_ollama'
  durationMs: number
  error: string | null
  tagsData: Record<string, unknown>
  psData: Record<string, unknown>
  versionData: Record<string, unknown>
  hostUpdate: {
    status: string
    latencyMs: number
    apiVersion: string | null
    gpu: string | null
    gpuVramMb: number | null
    lastError: string | null
  }
}

const DEFAULT_PORT = 4002
const proxyUrl = process.env.PROBE_SIDECAR_PROXY_URL || process.env.ALL_PROXY || process.env.HTTPS_PROXY || process.env.HTTP_PROXY
if (proxyUrl && proxyUrl.trim().length > 0) {
  setGlobalDispatcher(new ProxyAgent(proxyUrl.trim()))
  console.log(`[probe-sidecar] outbound HTTP proxy enabled: ${proxyUrl.trim()}`)
}
const app = express()
app.use(express.json({ limit: '10mb' }))

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const fetchJsonWithTimeout = async (url: string, timeoutMs: number) => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    const text = await response.text()
    let data: Record<string, unknown> = {}
    if (text) {
      try {
        data = JSON.parse(text) as Record<string, unknown>
      } catch {
        data = {}
      }
    }
    return { response, data, text }
  } finally {
    clearTimeout(timer)
  }
}

const inferGpuState = (tagsData: Record<string, unknown>, psData: Record<string, unknown>) => {
  let gpuDetected = false
  let totalVram = 0

  const psModels = Array.isArray(psData.models) ? psData.models : []
  for (const model of psModels) {
    if (typeof model === 'object' && model && 'size_vram' in model) {
      const vram = Number((model as Record<string, unknown>).size_vram || 0)
      if (Number.isFinite(vram) && vram > 0) {
        totalVram += Math.trunc(vram)
        gpuDetected = true
      }
    }
  }

  const tagModels = Array.isArray(tagsData.models) ? tagsData.models : []
  if (!gpuDetected) {
    for (const model of tagModels) {
      if (typeof model !== 'object' || !model) {
        continue
      }

      const record = model as Record<string, unknown>
      const modelSize = Number(record.size || 0)
      if (Number.isFinite(modelSize) && modelSize > 10 * 1024 * 1024 * 1024) {
        gpuDetected = true
        break
      }

      const details = typeof record.details === 'object' && record.details ? (record.details as Record<string, unknown>) : {}
      const parameterSize = typeof details.parameter_size === 'string' ? details.parameter_size : ''
      const match = parameterSize.match(/(\d+(?:\.\d+)?)[Bb]/)
      if (match && Number(match[1]) >= 13) {
        gpuDetected = true
        break
      }
    }
  }

  return {
    gpu: gpuDetected || totalVram > 0 ? 'available' : null,
    gpuVramMb: totalVram > 0 ? Math.trunc(totalVram / (1024 * 1024)) : null,
  }
}

const limitTagsPayload = (tagsData: Record<string, unknown>) => {
  const limited = { ...tagsData }
  if (Array.isArray(limited.models) && limited.models.length > 10) {
    limited.total_models = limited.models.length
    limited.models = limited.models.slice(0, 10)
  }
  return limited
}

const probeHost = async (
  host: HostInput,
  timeoutSeconds: number,
  retries: number,
): Promise<ProbeBatchResult> => {
  const start = Date.now()
  const baseUrl = `http://${host.ip}:${host.port}`

  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      const timeoutMs = timeoutSeconds * 1000
      const [tagsResult, psResult, versionResult] = await Promise.all([
        fetchJsonWithTimeout(`${baseUrl}/api/tags`, timeoutMs),
        fetchJsonWithTimeout(`${baseUrl}/api/ps`, timeoutMs),
        fetchJsonWithTimeout(`${baseUrl}/api/version`, timeoutMs),
      ])

      const durationMs = Date.now() - start

      if (tagsResult.response.status === 200) {
        const tagsData = limitTagsPayload(tagsResult.data)
        const psData = psResult.response.status === 200 ? psResult.data : {}
        const versionData = versionResult.response.status === 200 ? versionResult.data : {}
        const gpuState = inferGpuState(tagsResult.data, psData)

        return {
          hostId: host.hostId,
          status: 'success',
          durationMs,
          error: null,
          tagsData,
          psData,
          versionData,
          hostUpdate: {
            status: 'online',
            latencyMs: durationMs,
            apiVersion: typeof versionData.version === 'string' ? versionData.version : 'unknown',
            gpu: gpuState.gpu,
            gpuVramMb: gpuState.gpuVramMb,
            lastError: null,
          },
        }
      }

      if (tagsResult.response.status >= 400 && tagsResult.response.status < 500) {
        return {
          hostId: host.hostId,
          status: 'non_ollama',
          durationMs,
          error: `HTTP ${tagsResult.response.status}`,
          tagsData: {},
          psData: {},
          versionData: {},
          hostUpdate: {
            status: 'non_ollama',
            latencyMs: durationMs,
            apiVersion: null,
            gpu: null,
            gpuVramMb: null,
            lastError: `HTTP ${tagsResult.response.status}`,
          },
        }
      }
    } catch (error) {
      const durationMs = Date.now() - start
      const message = error instanceof Error ? error.message : 'unknown error'
      const isTimeout = message.toLowerCase().includes('abort') || message.toLowerCase().includes('timeout')

      if (attempt === retries - 1) {
        return {
          hostId: host.hostId,
          status: isTimeout ? 'timeout' : 'error',
          durationMs,
          error: isTimeout ? 'Connection timeout' : message,
          tagsData: {},
          psData: {},
          versionData: {},
          hostUpdate: {
            status: isTimeout ? 'timeout' : 'error',
            latencyMs: durationMs,
            apiVersion: null,
            gpu: null,
            gpuVramMb: null,
            lastError: isTimeout ? 'Connection timeout' : message,
          },
        }
      }

      await sleep((isTimeout ? 1000 : 500) * 2 ** attempt)
    }
  }

  return {
    hostId: host.hostId,
    status: 'error',
    durationMs: Date.now() - start,
    error: 'All retries exhausted',
    tagsData: {},
    psData: {},
    versionData: {},
    hostUpdate: {
      status: 'error',
      latencyMs: Date.now() - start,
      apiVersion: null,
      gpu: null,
      gpuVramMb: null,
      lastError: 'All retries exhausted',
    },
  }
}

const runWithConcurrency = async <TInput, TOutput>(
  items: TInput[],
  concurrency: number,
  worker: (item: TInput) => Promise<TOutput>,
) => {
  const results: TOutput[] = new Array(items.length)
  let cursor = 0

  const runners = Array.from({ length: Math.max(1, concurrency) }, async () => {
    while (true) {
      const current = cursor
      cursor += 1
      if (current >= items.length) {
        return
      }
      results[current] = await worker(items[current])
    }
  })

  await Promise.all(runners)
  return results
}

app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: 'probe-sidecar', timestamp: new Date().toISOString() })
})

app.post('/probe-batch', async (req: Request, res: Response) => {
  const body = req.body as ProbeBatchRequest
  const hosts = Array.isArray(body.hosts) ? body.hosts : []
  const timeoutSeconds = Math.max(1, body.timeoutSeconds || 5)
  const retries = Math.max(1, body.retries || 2)
  const concurrency = Math.max(1, Math.min(body.concurrency || 50, 500))

  if (hosts.length === 0) {
    res.status(400).json({ error: 'hosts array is required' })
    return
  }

  const startedAt = Date.now()
  const results = await runWithConcurrency(hosts, concurrency, (host) => probeHost(host, timeoutSeconds, retries))

  res.json({
    processed: results.length,
    durationMs: Date.now() - startedAt,
    results,
  })
})

app.listen(DEFAULT_PORT, '0.0.0.0', () => {
  console.log(`probe-sidecar listening on http://0.0.0.0:${DEFAULT_PORT}`)
})
