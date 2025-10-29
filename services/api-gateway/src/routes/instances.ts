import express from 'express';
import { query, param, validationResult } from 'express-validator';
import { asyncHandler, createError } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';

const router = express.Router();

// Get Ollama instances with filtering and pagination
router.get('/', [
  query('page').optional().isInt({ min: 1 }),
  query('limit').optional().isInt({ min: 1, max: 1000 }),
  query('status').optional().isIn(['active', 'inactive', 'error']),
  query('gpu_capable').optional().isBoolean(),
  query('version').optional().isString().trim()
], asyncHandler(async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
  }

  const db = getDatabase();
  const {
    page = 1,
    limit = 50,
    status,
    gpu_capable,
    version
  } = req.query;

  let query = db('ollama_instances as oi')
    .join('hosts as h', 'oi.host_id', 'h.id')
    .select(
      'oi.*',
      'h.host',
      'h.port',
      'h.geographic_location',
      'h.organization'
    );

  // Apply filters
  if (status) {
    query = query.where('oi.status', status);
  }

  if (gpu_capable !== undefined) {
    query = query.where('oi.gpu_capable', gpu_capable === 'true');
  }

  if (version) {
    query = query.where('oi.ollama_version', 'like', `%${version}%`);
  }

  // Count total
  const countQuery = db(query.as('counted')).count('* as total').first();
  const total = await countQuery;

  // Apply pagination and ordering
  const offset = (parseInt(page as string) - 1) * parseInt(limit as string);
  const instances = await query
    .orderBy('oi.last_scanned', 'desc')
    .limit(parseInt(limit as string))
    .offset(offset);

  res.json({
    instances: instances.map(instance => ({
      ...instance,
      last_scanned: new Date(instance.last_scanned).toISOString(),
      created_at: new Date(instance.created_at).toISOString(),
      updated_at: new Date(instance.updated_at).toISOString()
    })),
    pagination: {
      page: parseInt(page as string),
      limit: parseInt(limit as string),
      total: total?.total || 0,
      pages: Math.ceil((total?.total || 0) / parseInt(limit as string))
    }
  });
}));

// Get specific instance details with models
router.get('/:instanceId', [
  param('instanceId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { instanceId } = req.params;

  const instance = await db('ollama_instances as oi')
    .join('hosts as h', 'oi.host_id', 'h.id')
    .select(
      'oi.*',
      'h.host',
      'h.port',
      'h.geographic_location',
      'h.organization',
      'h.source_data'
    )
    .where('oi.id', instanceId)
    .first();

  if (!instance) {
    throw createError('Ollama instance not found', 404);
  }

  // Get available models
  const models = await db('models')
    .where('ollama_instance_id', instanceId)
    .select('*')
    .orderBy('name');

  // Get loaded models
  const loadedModels = await db('loaded_models')
    .where('ollama_instance_id', instanceId)
    .select('*')
    .orderBy('loaded_at', 'desc');

  res.json({
    ...instance,
    models: models.map(model => ({
      ...model,
      created_at: new Date(model.created_at).toISOString(),
      modified_at: model.modified_at ? new Date(model.modified_at).toISOString() : null
    })),
    loaded_models: loadedModels.map(model => ({
      ...model,
      loaded_at: new Date(model.loaded_at).toISOString(),
      expires_at: model.expires_at ? new Date(model.expires_at).toISOString() : null
    })),
    last_scanned: new Date(instance.last_scanned).toISOString(),
    created_at: new Date(instance.created_at).toISOString(),
    updated_at: new Date(instance.updated_at).toISOString()
  });
}));

// Rescan specific instance
router.post('/:instanceId/rescan', [
  param('instanceId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { instanceId } = req.params;

  // Get instance details
  const instance = await db('ollama_instances as oi')
    .join('hosts as h', 'oi.host_id', 'h.id')
    .select('oi.id', 'h.id as host_id', 'h.host', 'h.port')
    .where('oi.id', instanceId)
    .first();

  if (!instance) {
    throw createError('Ollama instance not found', 404);
  }

  // Create a single-host scan job
  const [scanJobId] = await db('scan_jobs').insert({
    name: `Rescan ${instance.host}:${instance.port}`,
    host_count: 1,
    status: 'pending',
    max_concurrent: 1,
    timeout_seconds: 10,
    created_at: new Date().toISOString()
  });

  // Link the host to the scan job
  await db('scan_job_hosts').insert({
    scan_job_id: scanJobId,
    host_id: instance.host_id
  });

  // TODO: Trigger the scan (would call scanner service)
  
  res.json({
    success: true,
    message: 'Rescan initiated',
    scan_job_id: scanJobId
  });
}));

// Delete instance (and models)
router.delete('/:instanceId', [
  param('instanceId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { instanceId } = req.params;

  const deleted = await db('ollama_instances')
    .where('id', instanceId)
    .del();

  if (deleted === 0) {
    throw createError('Ollama instance not found', 404);
  }

  res.json({
    success: true,
    message: 'Ollama instance deleted successfully'
  });
}));

export default router;