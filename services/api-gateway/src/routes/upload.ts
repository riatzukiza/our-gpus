import express from 'express';
import multer from 'multer';
import { v4 as uuidv4 } from 'uuid';
import path from 'path';
import fs from 'fs/promises';
import { body, validationResult } from 'express-validator';
import { asyncHandler, createError } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';
import { config } from '../config';
import { logger } from '../utils/logger';
import axios from 'axios';

const router = express.Router();

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: async (req, file, cb) => {
    await fs.mkdir(config.upload.uploadDir, { recursive: true });
    cb(null, config.upload.uploadDir);
  },
  filename: (req, file, cb) => {
    const uniqueName = `${uuidv4()}-${file.originalname}`;
    cb(null, uniqueName);
  }
});

const upload = multer({
  storage,
  limits: {
    fileSize: config.upload.maxFileSizeGB * 1024 * 1024 * 1024 // Convert GB to bytes
  },
  fileFilter: (req, file, cb) => {
    if (config.upload.allowedTypes.includes(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error(`File type not allowed. Allowed types: ${config.upload.allowedTypes.join(', ')}`));
    }
  }
});

// Upload endpoint
router.post('/', 
  upload.single('file'),
  [
    body('extractFields').optional().isArray(),
    body('batchSize').optional().isInt({ min: 100, max: 10000 })
  ],
  asyncHandler(async (req, res) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
      throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
    }

    if (!req.file) {
      throw createError('No file uploaded', 400);
    }

    const db = getDatabase();
    
    // Create upload job record
    const [jobId] = await db('upload_jobs').insert({
      filename: req.file.filename,
      original_filename: req.file.originalname,
      file_size: req.file.size,
      status: 'pending',
      created_at: new Date().toISOString()
    });

    logger.info('File upload initiated', {
      jobId,
      filename: req.file.originalname,
      size: req.file.size
    });

    // Start processing asynchronously
    processUploadAsync(jobId, req.file.filename, req.body.extractFields, req.body.batchSize)
      .catch(error => {
        logger.error('Upload processing failed:', { jobId, error: error.message });
      });

    res.json({
      success: true,
      jobId,
      filename: req.file.originalname,
      size: req.file.size,
      message: 'File uploaded successfully. Processing started.'
    });
  })
);

// Get upload job status
router.get('/:jobId/status', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { jobId } = req.params;

  const job = await db('upload_jobs')
    .where('id', jobId)
    .first();

  if (!job) {
    throw createError('Upload job not found', 404);
  }

  // Get processed host count
  const hostCount = await db('hosts')
    .where('upload_job_id', jobId)
    .count('id as count')
    .first();

  res.json({
    ...job,
    processed_hosts: hostCount?.count || 0
  });
}));

// List recent upload jobs
router.get('/', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const page = parseInt(req.query.page as string) || 1;
  const limit = parseInt(req.query.limit as string) || 20;
  const offset = (page - 1) * limit;

  const jobs = await db('upload_jobs')
    .select('*')
    .orderBy('created_at', 'desc')
    .limit(limit)
    .offset(offset);

  // Get host counts for each job
  const jobsWithCounts = await Promise.all(
    jobs.map(async (job) => {
      const hostCount = await db('hosts')
        .where('upload_job_id', job.id)
        .count('id as count')
        .first();
      
      return {
        ...job,
        host_count: hostCount?.count || 0
      };
    })
  );

  const total = await db('upload_jobs').count('id as count').first();

  res.json({
    jobs: jobsWithCounts,
    pagination: {
      page,
      limit,
      total: total?.count || 0,
      pages: Math.ceil((total?.count || 0) / limit)
    }
  });
}));

// Delete upload job and associated data
router.delete('/:jobId', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const { jobId } = req.params;

  const job = await db('upload_jobs')
    .where('id', jobId)
    .first();

  if (!job) {
    throw createError('Upload job not found', 404);
  }

  // Delete associated file if it exists
  try {
    await fs.unlink(path.join(config.upload.uploadDir, job.filename));
  } catch (error) {
    logger.warn('Could not delete uploaded file:', { filename: job.filename, error });
  }

  // Delete database records (cascade will handle related data)
  await db('upload_jobs').where('id', jobId).del();

  logger.info('Upload job deleted', { jobId });

  res.json({
    success: true,
    message: 'Upload job deleted successfully'
  });
}));

// Async processing function
async function processUploadAsync(
  jobId: number, 
  filename: string, 
  extractFields?: string[], 
  batchSize: number = 1000
) {
  const db = getDatabase();
  
  try {
    // Update job status
    await db('upload_jobs')
      .where('id', jobId)
      .update({ 
        status: 'processing',
        updated_at: new Date().toISOString()
      });

    // Call JSON processor service
    const response = await axios.post(`${config.services.jsonProcessor.url}/process`, {
      filename,
      jobId,
      extractFields,
      batchSize
    }, {
      timeout: 30 * 60 * 1000 // 30 minutes timeout for large files
    });

    if (response.data.success) {
      await db('upload_jobs')
        .where('id', jobId)
        .update({
          status: 'completed',
          total_records: response.data.totalRecords,
          processed_records: response.data.processedRecords,
          completed_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        });
    } else {
      throw new Error(response.data.error || 'Processing failed');
    }

    logger.info('Upload processing completed', {
      jobId,
      totalRecords: response.data.totalRecords,
      processedRecords: response.data.processedRecords
    });

  } catch (error) {
    logger.error('Upload processing failed:', { jobId, error: error.message });
    
    await db('upload_jobs')
      .where('id', jobId)
      .update({
        status: 'failed',
        error_message: error.message,
        updated_at: new Date().toISOString()
      });
  }
}

export default router;