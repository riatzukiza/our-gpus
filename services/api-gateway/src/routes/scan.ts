import express from 'express';
import { body, param, validationResult } from 'express-validator';
import { asyncHandler, createError } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';
import { config } from '../config';
import { logger } from '../utils/logger';
import axios from 'axios';

const router = express.Router();

// Start new scan job
router.post('/', [
  body('name').isString().trim().isLength({ min: 1, max: 255 }),
  body('upload_job_id').optional().isInt({ min: 1 }),
  body('host_filters').optional().isObject(),
  body('max_concurrent').optional().isInt({ min: 1, max: 500 }),
  body('timeout_seconds').optional().isInt({ min: 1, max: 60 })
], asyncHandler(async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
  }

  const db = getDatabase();
  const {
    name,
    upload_job_id,
    host_filters = {},
    max_concurrent = config.scanning.defaultMaxConcurrent,
    timeout_seconds = config.scanning.defaultTimeout
  } = req.body;

  try {
    // Get hosts to scan
    let hostQuery = db('hosts as h')
      .select('h.id as host_id', 'h.host', 'h.port')
      .where('h.id', '>', 0); // Basic filter

    // Apply upload job filter if specified
    if (upload_job_id) {
      hostQuery = hostQuery.where('h.upload_job_id', upload_job_id);
    }

    // Apply additional host filters
    if (host_filters.location) {
      hostQuery = hostQuery.where('h.geographic_location', 'like', `%${host_filters.location}%`);
    }
    
    if (host_filters.organization) {
      hostQuery = hostQuery.where('h.organization', 'like', `%${host_filters.organization}%`);
    }

    // Get hosts that haven't been scanned recently or failed
    hostQuery = hostQuery.leftJoin('ollama_instances as oi', 'h.id', 'oi.host_id')
      .where(function() {
        this.whereNull('oi.id') // Never scanned
            .orWhere('oi.status', 'error') // Previous error
            .orWhere('oi.last_scanned', '<', new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()); // Older than 24h
      });

    const hosts = await hostQuery;

    if (hosts.length === 0) {
      throw createError('No hosts found matching the specified criteria', 400);
    }

    // Create scan job
    const [scanJobId] = await db('scan_jobs').insert({
      name,
      host_count: hosts.length,
      status: 'pending',
      max_concurrent,
      timeout_seconds,
      created_at: new Date().toISOString()
    });

    // Link hosts to scan job
    const scanJobHosts = hosts.map(host => ({
      scan_job_id: scanJobId,
      host_id: host.host_id
    }));

    await db('scan_job_hosts').insert(scanJobHosts);

    logger.info('Scan job created', {
      scanJobId,
      name,
      hostCount: hosts.length,
      maxConcurrent: max_concurrent,
      timeout: timeout_seconds
    });

    // Start scanning asynchronously by calling the scanner service
    startScanAsync(scanJobId, hosts, max_concurrent, timeout_seconds)
      .catch(error => {
        logger.error('Failed to start scan:', { scanJobId, error: error.message });
      });

    res.json({
      success: true,
      scan_job_id: scanJobId,
      name,
      host_count: hosts.length,
      status: 'pending',
      message: 'Scan job created and started'
    });

  } catch (error) {
    logger.error('Scan creation failed:', error);
    throw error;
  }
}));

// Get scan job status
router.get('/:jobId', [
  param('jobId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { jobId } = req.params;

  const scanJob = await db('scan_jobs')
    .where('id', jobId)
    .first();

  if (!scanJob) {
    throw createError('Scan job not found', 404);
  }

  // Get additional stats if job is running or completed
  let recentResults = null;
  if (scanJob.status !== 'pending') {
    recentResults = await db('ollama_instances as oi')
      .join('scan_job_hosts as sjh', 'oi.host_id', 'sjh.host_id')
      .where('sjh.scan_job_id', jobId)
      .select(
        'oi.status',
        'oi.gpu_capable',
        'oi.ollama_version'
      );
  }

  res.json({
    ...scanJob,
    recent_results: recentResults
  });
}));

// List scan jobs
router.get('/', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const page = parseInt(req.query.page as string) || 1;
  const limit = parseInt(req.query.limit as string) || 20;
  const status = req.query.status as string;

  let query = db('scan_jobs').select('*');
  
  if (status && ['pending', 'running', 'completed', 'failed', 'cancelled'].includes(status)) {
    query = query.where('status', status);
  }

  const offset = (page - 1) * limit;
  const jobs = await query
    .orderBy('created_at', 'desc')
    .limit(limit)
    .offset(offset);

  const total = await db('scan_jobs')
    .count('id as count')
    .where(status ? { status } : {})
    .first();

  res.json({
    jobs,
    pagination: {
      page,
      limit,
      total: total?.count || 0,
      pages: Math.ceil((total?.count || 0) / limit)
    }
  });
}));

// Cancel scan job
router.post('/:jobId/cancel', [
  param('jobId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { jobId } = req.params;

  const updated = await db('scan_jobs')
    .where('id', jobId)
    .where('status', 'in', ['pending', 'running'])
    .update({
      status: 'cancelled',
      updated_at: new Date().toISOString()
    });

  if (updated === 0) {
    throw createError('Scan job not found or cannot be cancelled', 404);
  }

  logger.info('Scan job cancelled', { jobId });

  res.json({
    success: true,
    message: 'Scan job cancelled'
  });
}));

// Delete scan job and results
router.delete('/:jobId', [
  param('jobId').isInt({ min: 1 })
], asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { jobId } = req.params;

  // Verify job exists
  const job = await db('scan_jobs').where('id', jobId).first();
  if (!job) {
    throw createError('Scan job not found', 404);
  }

  // Don't delete running jobs
  if (job.status === 'running') {
    throw createError('Cannot delete running scan job. Cancel it first.', 400);
  }

  // Delete will cascade to scan_job_hosts due to foreign key constraints
  await db('scan_jobs').where('id', jobId).del();

  logger.info('Scan job deleted', { jobId });

  res.json({
    success: true,
    message: 'Scan job deleted'
  });
}));

// Async function to start scanning
async function startScanAsync(
  scanJobId: number, 
  hosts: any[], 
  maxConcurrent: number, 
  timeout: number
) {
  try {
    // Call the Ollama scanner service
    const response = await axios.post(`${config.services.ollamaScanner.url}/scan`, {
      hosts,
      scan_job_id: scanJobId,
      max_concurrent: maxConcurrent,
      timeout: timeout,
      max_retries: config.scanning.maxRetries
    }, {
      timeout: 5 * 60 * 1000 // 5 minutes for the initial request
    });

    if (!response.data.success) {
      throw new Error(response.data.message || 'Scanner service returned error');
    }

    logger.info('Scan started successfully', {
      scanJobId,
      hostCount: hosts.length
    });

  } catch (error) {
    logger.error('Failed to start scan via scanner service:', {
      scanJobId,
      error: error.message
    });

    // Update job status to failed
    const db = getDatabase();
    await db('scan_jobs')
      .where('id', scanJobId)
      .update({
        status: 'failed',
        updated_at: new Date().toISOString()
      });
  }
}

export default router;