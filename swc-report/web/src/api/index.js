import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// ── Pipelines ─────────────────────────────────────────
export const createRun = (data) => api.post('/pipelines', data)
export const listRuns = () => api.get('/pipelines')
export const getRun = (id) => api.get(`/pipelines/${id}`)
export const deleteRun = (id) => api.delete(`/pipelines/${id}`)
export const getAudit = (id) => api.get(`/pipelines/${id}/audit`)
export const getChapters = (id) => api.get(`/pipelines/${id}/chapters`)

// SSE progress stream
export function streamProgress(runId, onEvent, onDone) {
  const evtSource = new EventSource(`/api/pipelines/${runId}/progress`)
  evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data.step === '__done__') {
      evtSource.close()
      if (onDone) onDone()
    } else {
      onEvent(data)
    }
  }
  evtSource.onerror = () => {
    evtSource.close()
    if (onDone) onDone()
  }
  return evtSource
}

// Download helpers
export const downloadResult = (id) => `/api/pipelines/${id}/result`
export const downloadDraft = (id) => `/api/pipelines/${id}/draft`

// ── Config ────────────────────────────────────────────
export const getFacts = () => api.get('/config/facts')
export const updateFacts = (data) => api.put('/config/facts', data)
export const getMeasures = () => api.get('/config/measures')
export const updateMeasures = (data) => api.put('/config/measures', data)
export const uploadFacts = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/config/upload/facts', form)
}
export const uploadMeasures = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/config/upload/measures', form)
}
export const validateConfig = (data) => api.post('/config/validate', data)

// ── System ────────────────────────────────────────────
export const healthCheck = () => api.get('/system/health')
export const getSettings = () => api.get('/system/settings')
export const updateSettings = (data) => api.put('/system/settings', data)

// ── Vision (VL) ──────────────────────────────────────
export const vlHealthCheck = () => api.get('/vision/health')
export const uploadDocuments = (files, projectId) => {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  if (projectId) form.append('project_id', projectId)
  return api.post('/vision/upload', form, { timeout: 60000 })
}
export const vlExtractInfo = (projectId, fileNames) =>
  api.post('/vision/extract', { project_id: projectId, file_names: fileNames }, { timeout: 600000 })
export const vlGenerateSiteDesc = (projectId, fileNames) =>
  api.post('/vision/site-desc', { project_id: projectId, file_names: fileNames }, { timeout: 600000 })
export const listUploadedFiles = (projectId) =>
  api.get('/vision/files', { params: { project_id: projectId } })
export const clearUploadedFiles = (projectId) =>
  api.delete('/vision/files', { params: { project_id: projectId } })
export const loadSampleData = (sampleName) =>
  api.post('/vision/load-sample', null, { params: { sample_name: sampleName } })

// ── CAD / GIS ────────────────────────────────────────
export const cadConvert = (projectId, fileNames) =>
  api.post('/vision/cad-convert', { project_id: projectId, file_names: fileNames }, { timeout: 300000 })
export const gisValidateZones = (projectId, fileNames) =>
  api.post('/vision/gis-validate', { project_id: projectId, file_names: fileNames }, { timeout: 120000 })
export const gisExtractZones = (projectId, fileNames) =>
  api.post('/vision/gis-extract-zones', { project_id: projectId, file_names: fileNames }, { timeout: 120000 })

// ── Knowledge ────────────────────────────────────────
export const listConfigFiles = () => api.get('/knowledge/config-files')
export const getConfigFile = (key) => api.get(`/knowledge/config-files/${key}`)
export const updateConfigFile = (key, data) => api.put(`/knowledge/config-files/${key}`, data)
export const listAtlasFiles = () => api.get('/knowledge/atlas')
export const uploadAtlasFile = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/knowledge/atlas/upload', form, { timeout: 60000 })
}
export const deleteAtlasFile = (name) => api.delete(`/knowledge/atlas/${encodeURIComponent(name)}`)
export const reindexAtlas = () => api.post('/knowledge/atlas/reindex')
export const getAtlasReindexStatus = () => api.get('/knowledge/atlas/reindex/status')
export const listCorpusFiles = () => api.get('/knowledge/corpus')
export const uploadCorpusFile = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/knowledge/corpus/upload', form, { timeout: 60000 })
}
export const deleteCorpusFile = (name) => api.delete(`/knowledge/corpus/${encodeURIComponent(name)}`)
export const reindexCorpus = () => api.post('/knowledge/corpus/reindex')
export const getCorpusReindexStatus = () => api.get('/knowledge/corpus/reindex/status')
export const generateMeasureLibrary = () => api.post('/knowledge/generate/measure-library', null, { timeout: 300000 })
export const getGenerateStatus = () => api.get('/knowledge/generate/status')

export default api
