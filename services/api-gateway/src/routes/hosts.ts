import express from 'express';
import { query, param, validationResult } from 'express-validator';
import { asyncHandler, createError } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';

const router = express.Router();

// Get hosts with pagination and filtering
router.get('/', [
  query('page').optional().isInt({ min: 1 }),
  query('limit').optional().isInt({ min: 1, max: 1000 }),
  query('upload_job_id').optional().isInt({ min: 1 }),
  query('scanned').optional().isBoolean(),
  query('location').optional().isString().trim(),
  query('organization').optional().isString().trim()
], asyncHandler(async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
  }

  const db = getDatabase();
  const {
    page = 1,
    limit = 50,
    upload_job_id,
    scanned,
    location,
    organization
  } = req.query;

  let query = db('hosts as h')
    .leftJoin('ollama_instances as oi', 'h.id', 'oi.host_id')
    .select(
      'h.*',
      'oi.status as scan_status',
      'oi.last_scanned',
      'oi.ollama_version',
      'oi.gpu_capable',
      'oi.total_vram_bytes'
    );

  // Apply filters
  if (upload_job_id) {
    query = query.where('h.upload_job_id', upload_job_id);
  }

  if (scanned !== undefined) {
    if (scanned === 'true') {
      query = query.whereNotNull('oi.id');
    } else {
      query = query.whereNull('oi.id');
    }
  }

  if (location) {
    query = query.where('h.geographic_location', 'like', `%${location}%`);
  }

  if (organization) {
    query = query.where('h.organization', 'like', `%${organization}%`);
  }

  // Count total
  const countQuery = db(query.as('counted')).count('* as total').first();
  const total = await countQuery;

  // Apply pagination
  const offset = (parseInt(page as string) - 1) * parseInt(limit as string);
  const hosts = await query
    .orderBy('h.created_at', 'desc')
    .limit(parseInt(limit as string))
    .offset(offset);

  res.json({
    hosts: hosts.map(host => ({
      ...host,
      last_scanned: host.last_scanned ? new Date(host.last_scanned).toISOString() : null,
      created_at: new Date(host.created_at).toISOString()
    })),
    pagination: {
      page: parseInt(page as string),
      limit: parseInt(limit as string),
      total: total?.total || 0,
      pages: Math.ceil((total?.total || 0) / parseInt(limit as string))
    }
  });
}));

// Get specific host details
router.get('/:hostId', [
  param('hostId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { hostId } = req.params;

  const host = await db('hosts as h')
    .leftJoin('ollama_instances as oi', 'h.id', 'oi.host_id')
    .leftJoin('upload_jobs as uj', 'h.upload_job_id', 'uj.id')
    .select(
      'h.*',
      'oi.id as instance_id',
      'oi.status as scan_status',
      'oi.last_scanned',
      'oi.ollama_version',
      'oi.gpu_capable',
      'oi.total_vram_bytes',
      'oi.system_info',
      'oi.error_message',
      'uj.original_filename as source_file'
    )
    .where('h.id', hostId)
    .first();

  if (!host) {
    throw createError('Host not found', 404);
  }

  // Get models if instance exists
  let models = [];
  if (host.instance_id) {
    models = await db('models')
      .where('ollama_instance_id', host.instance_id)
      .select('*')
      .orderBy('name');
  }

  // Get loaded models
  let loadedModels = [];
  if (host.instance_id) {
    loadedModels = await db('loaded_models')
      .where('ollama_instance_id', host.instance_id)
      .select('*')
      .orderBy('loaded_at', 'desc');
  }

  res.json({
    ...host,
    models,
    loaded_models: loadedModels,
    last_scanned: host.last_scanned ? new Date(host.last_scanned).toISOString() : null,
    created_at: new Date(host.created_at).toISOString()
  });
}));

// Delete host (and associated data)
router.delete('/:hostId', [
  param('hostId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { hostId } = req.params;

  const deleted = await db('hosts')
    .where('id', hostId)
    .del();

  if (deleted === 0) {
    throw createError('Host not found', 404);
  }

  res.json({
    success: true,
    message: 'Host deleted successfully'
  });
}));

export default router;