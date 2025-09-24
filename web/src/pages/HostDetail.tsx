import { useParams } from 'react-router-dom'
import { useQuery } from 'react-query'
import axios from 'axios'
import { format } from 'date-fns'
import { Cpu, HardDrive, Clock, Globe, Server, Zap, Send } from 'lucide-react'
import { useState } from 'react'

export default function HostDetail() {
  const { id } = useParams<{ id: string }>()
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [prompt, setPrompt] = useState<string>('')
  const [isRunning, setIsRunning] = useState(false)
  const [promptResponse, setPromptResponse] = useState<any>(null)
  const [promptError, setPromptError] = useState<string | null>(null)
  const [streamingResponse, setStreamingResponse] = useState<string>('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [useStreaming, setUseStreaming] = useState(true)
  
  const { data: host, isLoading } = useQuery(
    ['host', id],
    async () => {
      const response = await axios.get(`/api/hosts/${id}`)
      return response.data
    }
  )
  
  const runPrompt = async () => {
    if (!selectedModel || !prompt.trim()) return
    
    setIsRunning(true)
    setPromptError(null)
    setPromptResponse(null)
    setStreamingResponse('')
    
    if (useStreaming) {
      // Use streaming endpoint
      setIsStreaming(true)
      
      try {
        const response = await fetch(`/api/hosts/${id}/prompt/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            host_id: parseInt(id!),
            model: selectedModel,
            prompt: prompt,
            stream: true
          })
        })
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${await response.text()}`)
        }
        
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()
        let accumulatedResponse = ''
        let metrics: any = {}
        
        if (reader) {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            
            const chunk = decoder.decode(value)
            const lines = chunk.split('\n')
            
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6))
                  
                  if (data.error) {
                    setPromptError(data.error)
                    setIsStreaming(false)
                    setIsRunning(false)
                    return
                  }
                  
                  if (data.content) {
                    accumulatedResponse += data.content
                    setStreamingResponse(accumulatedResponse)
                  }
                  
                  // Capture metrics from the final chunk
                  if (data.done) {
                    metrics = {
                      total_duration: data.total_duration,
                      load_duration: data.load_duration,
                      prompt_eval_duration: data.prompt_eval_duration,
                      eval_duration: data.eval_duration,
                      eval_count: data.eval_count
                    }
                  }
                } catch (e) {
                  console.error('Error parsing SSE data:', e)
                }
              }
            }
          }
        }
        
        // Set final response with metrics
        setPromptResponse({
          success: true,
          response: accumulatedResponse,
          ...metrics
        })
        setIsStreaming(false)
        
      } catch (error: any) {
        setPromptError(error.message || 'Failed to stream prompt')
        setIsStreaming(false)
      } finally {
        setIsRunning(false)
      }
    } else {
      // Use non-streaming endpoint (existing code)
      try {
        const response = await axios.post(`/api/hosts/${id}/prompt`, {
          host_id: parseInt(id!),
          model: selectedModel,
          prompt: prompt,
          stream: false
        })
        
        if (response.data.success) {
          setPromptResponse(response.data)
        } else {
          setPromptError(response.data.error || 'Failed to run prompt')
        }
      } catch (error: any) {
        setPromptError(error.response?.data?.detail || error.message || 'Failed to run prompt')
      } finally {
        setIsRunning(false)
      }
    }
  }
  
  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    )
  }
  
  if (!host) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 dark:text-gray-400">Host not found</p>
      </div>
    )
  }
  
  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
          {host.ip}:{host.port}
        </h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="flex items-start">
            <Server className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Status</p>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100 capitalize">{host.status}</p>
            </div>
          </div>
          
          <div className="flex items-start">
            <Clock className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Last Seen</p>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                {format(new Date(host.last_seen), 'MMM d, yyyy HH:mm:ss')}
              </p>
            </div>
          </div>
          
          <div className="flex items-start">
            <Zap className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Latency</p>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                {host.latency_ms ? `${host.latency_ms.toFixed(0)}ms` : 'N/A'}
              </p>
            </div>
          </div>
          
          <div className="flex items-start">
            <Cpu className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">GPU</p>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                {host.gpu === 'available' || host.gpu_vram_mb ? 
                  (host.gpu_vram_mb ? 
                    `${(host.gpu_vram_mb / 1024).toFixed(1)}GB VRAM` : 
                    'GPU Available'
                  ) : 'CPU Only'}
              </p>
            </div>
          </div>
          
          <div className="flex items-start">
            <HardDrive className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">API Version</p>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">{host.api_version || 'Unknown'}</p>
            </div>
          </div>
          
          {host.geo_country && (
            <div className="flex items-start">
              <Globe className="w-5 h-5 text-gray-400 dark:text-gray-500 mt-1 mr-3" />
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Location</p>
                <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                  {host.geo_city ? `${host.geo_city}, ` : ''}{host.geo_country}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
      
      <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Available Models</h3>
        
        {host.models && host.models.length > 0 ? (
          <div className="space-y-3">
            {host.models.map((model: any, idx: number) => (
              <div key={idx} className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-900">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-gray-100">{model.name || model}</p>
                    {typeof model === 'object' && (
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {model.family && `Family: ${model.family}`}
                        {model.parameters && ` • ${model.parameters}`}
                      </p>
                    )}
                  </div>
                  {model.loaded && (
                    <span className="px-2 py-1 text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded">
                      Loaded
                    </span>
                  )}
                </div>
                {model.vram_usage_mb && (
                  <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                    VRAM Usage: {(model.vram_usage_mb / 1024).toFixed(2)}GB
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 dark:text-gray-400">No models found</p>
        )}
      </div>
      
      {/* Prompt Runner Section */}
      {host.status === 'online' && host.models && host.models.length > 0 && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Run Prompt</h3>
          
          <div className="space-y-4">
            {/* Model Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Select Model
              </label>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-blue-500 focus:border-blue-500"
                disabled={isRunning}
              >
                <option value="">Choose a model...</option>
                {host.models.map((model: any, idx: number) => (
                  <option key={idx} value={typeof model === 'string' ? model : model.name}>
                    {typeof model === 'string' ? model : model.name}
                  </option>
                ))}
              </select>
            </div>
            
            {/* Prompt Input */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Prompt
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Enter your prompt here..."
                disabled={isRunning}
              />
            </div>
            
            {/* Streaming Toggle and Run Button */}
            <div className="flex justify-between items-center">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={useStreaming}
                  onChange={(e) => setUseStreaming(e.target.checked)}
                  className="mr-2 rounded text-blue-600 focus:ring-blue-500"
                  disabled={isRunning}
                />
                <span className="text-sm text-gray-700 dark:text-gray-300">Stream response</span>
              </label>
              
              <button
                onClick={runPrompt}
                disabled={!selectedModel || !prompt.trim() || isRunning}
                className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isRunning ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    {isStreaming ? 'Streaming...' : 'Running...'}
                  </>
                ) : (
                  <>
                    <Send className="w-4 h-4 mr-2" />
                    Run Prompt
                  </>
                )}
              </button>
            </div>
            
            {/* Error Display */}
            {promptError && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-4">
                <p className="text-sm text-red-800 dark:text-red-200">{promptError}</p>
              </div>
            )}
            
            {/* Streaming Response Display */}
            {isStreaming && streamingResponse && (
              <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md p-4">
                <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
                  Response (streaming):
                </h4>
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <pre className="whitespace-pre-wrap text-gray-800 dark:text-gray-200 text-sm font-normal">
                    {streamingResponse}
                    <span className="inline-block w-2 h-4 bg-gray-500 dark:bg-gray-400 animate-pulse ml-1"></span>
                  </pre>
                </div>
              </div>
            )}
            
            {/* Final Response Display */}
            {!isStreaming && promptResponse && promptResponse.success && (
              <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md p-4">
                <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">Response:</h4>
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <pre className="whitespace-pre-wrap text-gray-800 dark:text-gray-200 text-sm font-normal">
                    {promptResponse.response}
                  </pre>
                </div>
                
                {/* Performance Metrics */}
                {(promptResponse.total_duration || promptResponse.eval_count) && (
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                    <h5 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Performance Metrics:</h5>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-gray-600 dark:text-gray-400">
                      {promptResponse.total_duration && (
                        <div>
                          <span className="font-medium">Total:</span> {(promptResponse.total_duration / 1e9).toFixed(2)}s
                        </div>
                      )}
                      {promptResponse.load_duration && (
                        <div>
                          <span className="font-medium">Load:</span> {(promptResponse.load_duration / 1e9).toFixed(2)}s
                        </div>
                      )}
                      {promptResponse.prompt_eval_duration && (
                        <div>
                          <span className="font-medium">Prompt Eval:</span> {(promptResponse.prompt_eval_duration / 1e9).toFixed(2)}s
                        </div>
                      )}
                      {promptResponse.eval_count && (
                        <div>
                          <span className="font-medium">Tokens:</span> {promptResponse.eval_count}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      
      {host.last_probe && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Last Probe Response</h3>
          <pre className="bg-gray-50 dark:bg-gray-900 p-4 rounded text-xs overflow-x-auto text-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-700">
            {JSON.stringify(host.last_probe, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}