import express from 'express';
import { query, validationResult } from 'express-validator';
import { asyncHandler, createError } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';

const router = express.Router();

// Advanced search with filters
router.get('/', [
  query('q').optional().isString().trim(),
  query('status').optional().isIn(['active', 'inactive', 'error']),
  query('gpu_capable').optional().isBoolean(),
  query('model').optional().isString().trim(),
  query('version').optional().isString().trim(),
  query('min_vram').optional().isInt({ min: 0 }),
  query('max_vram').optional().isInt({ min: 0 }),
  query('location').optional().isString().trim(),
  query('organization').optional().isString().trim(),
  query('page').optional().isInt({ min: 1 }),
  query('limit').optional().isInt({ min: 1, max: 1000 }),
  query('sort_by').optional().isIn(['host', 'last_scanned', 'models_found', 'vram_usage', 'version']),
  query('sort_order').optional().isIn(['asc', 'desc'])
], asyncHandler(async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
  }

  const db = getDatabase();
  
  // Parse query parameters
  const {
    q, status, gpu_capable, model, version, min_vram, max_vram,
    location, organization, page = 1, limit = 50,
    sort_by = 'last_scanned', sort_order = 'desc'
  } = req.query;

  // Build dynamic query
  let baseQuery = db('ollama_instances as oi')
    .join('hosts as h', 'oi.host_id', 'h.id')
    .leftJoin('models as m', 'oi.id', 'm.ollama_instance_id')
    .select(
      'oi.id',
      'h.host',
      'h.port',
      'oi.ollama_url',
      'oi.status',
      'oi.last_scanned',
      'oi.ollama_version',
      'oi.gpu_capable',
      'oi.total_vram_bytes',
      'oi.system_info',
      'h.geographic_location',
      'h.organization',
      db.raw('COUNT(DISTINCT m.id) as model_count'),
      db.raw('GROUP_CONCAT(DISTINCT m.name) as model_list')
    );

  // Apply filters
  if (q) {
    baseQuery = baseQuery.where(function() {
      this.where('h.host', 'like', `%${q}%`)
          .orWhere('oi.ollama_version', 'like', `%${q}%`)
          .orWhere('h.organization', 'like', `%${q}%`)
          .orWhere('h.geographic_location', 'like', `%${q}%`);
    });
  }

  if (status) {
    baseQuery = baseQuery.where('oi.status', status);
  }

  if (gpu_capable !== undefined) {
    baseQuery = baseQuery.where('oi.gpu_capable', gpu_capable === 'true');
  }

  if (model) {
    baseQuery = baseQuery.whereExists(function() {
      this.select('*')
          .from('models as m2')
          .whereRaw('m2.ollama_instance_id = oi.id')
          .where('m2.name', 'like', `%${model}%`);
    });
  }

  if (version) {
    baseQuery = baseQuery.where('oi.ollama_version', 'like', `%${version}%`);
  }

  if (min_vram) {
    baseQuery = baseQuery.where('oi.total_vram_bytes', '>=', parseInt(min_vram as string));
  }

  if (max_vram) {
    baseQuery = baseQuery.where('oi.total_vram_bytes', '<=', parseInt(max_vram as string));
  }

  if (location) {
    baseQuery = baseQuery.where('h.geographic_location', 'like', `%${location}%`);
  }

  if (organization) {
    baseQuery = baseQuery.where('h.organization', 'like', `%${organization}%`);
  }

  // Group by instance
  baseQuery = baseQuery.groupBy('oi.id', 'h.host', 'h.port', 'oi.ollama_url', 
    'oi.status', 'oi.last_scanned', 'oi.ollama_version', 'oi.gpu_capable', 
    'oi.total_vram_bytes', 'oi.system_info', 'h.geographic_location', 'h.organization');

  // Count total results before pagination
  const countQuery = db(baseQuery.as('counted')).count('* as total').first();
  const total = await countQuery;

  // Apply sorting
  const sortColumn = sort_by === 'host' ? 'h.host' :
                    sort_by === 'vram_usage' ? 'oi.total_vram_bytes' :
                    sort_by === 'models_found' ? 'model_count' :
                    sort_by === 'version' ? 'oi.ollama_version' :
                    'oi.last_scanned';

  baseQuery = baseQuery.orderBy(sortColumn, sort_order as 'asc' | 'desc');

  // Apply pagination
  const offset = (parseInt(page as string) - 1) * parseInt(limit as string);
  const results = await baseQuery.limit(parseInt(limit as string)).offset(offset);

  // Format results
  const formattedResults = results.map(result => ({
    ...result,
    model_list: result.model_list ? result.model_list.split(',') : [],
    last_scanned: new Date(result.last_scanned).toISOString()
  }));

  res.json({
    instances: formattedResults,
    pagination: {
      page: parseInt(page as string),
      limit: parseInt(limit as string),
      total: total?.total || 0,
      pages: Math.ceil((total?.total || 0) / parseInt(limit as string))
    },
    filters: {
      q, status, gpu_capable, model, version, min_vram, max_vram,
      location, organization, sort_by, sort_order
    }
  });
}));

// Get unique filter values for dropdowns
router.get('/filters', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const [versions, locations, organizations, models] = await Promise.all([
    // Unique Ollama versions
    db('ollama_instances')
      .distinct('ollama_version')
      .whereNotNull('ollama_version')
      .where('ollama_version', '!=', '')
      .orderBy('ollama_version'),

    // Unique locations
    db('hosts')
      .distinct('geographic_location')
      .whereNotNull('geographic_location')
      .where('geographic_location', '!=', '')
      .orderBy('geographic_location'),

    // Unique organizations
    db('hosts')
      .distinct('organization')
      .whereNotNull('organization')
      .where('organization', '!=', '')
      .orderBy('organization'),

    // Popular models
    db('models')
      .select('name')
      .count('* as count')
      .groupBy('name')
      .orderBy('count', 'desc')
      .limit(50)
  ]);

  res.json({
    versions: versions.map(v => v.ollama_version),
    locations: locations.map(l => l.geographic_location),
    organizations: organizations.map(o => o.organization),
    models: models.map(m => ({ name: m.name, count: m.count }))
  });
}));

// Export search results
router.get('/export', [
  query('format').optional().isIn(['csv', 'json']),
  query('q').optional().isString().trim(),
  query('status').optional().isIn(['active', 'inactive', 'error']),
  query('gpu_capable').optional().isBoolean(),
  query('model').optional().isString().trim()
], asyncHandler(async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw createError('Validation failed: ' + errors.array().map(e => e.msg).join(', '), 400);
  }

  const db = getDatabase();
  const { format = 'csv' } = req.query;

  // Use the same filtering logic as search but without pagination
  let query = db('ollama_instances as oi')
    .join('hosts as h', 'oi.host_id', 'h.id')
    .leftJoin('models as m', 'oi.id', 'm.ollama_instance_id')
    .select(
      'h.host',
      'h.port',
      'oi.status',
      'oi.ollama_version',
      'oi.gpu_capable',
      'oi.total_vram_bytes',
      'oi.last_scanned',
      'h.geographic_location',
      'h.organization',
      db.raw('GROUP_CONCAT(DISTINCT m.name) as models')
    )
    .groupBy('oi.id');

  // Apply same filters as search endpoint
  // ... (similar filtering logic)

  const results = await query;

  if (format === 'json') {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Content-Disposition', 'attachment; filename="ollama-instances.json"');
    res.json(results);
  } else {
    // CSV format
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename="ollama-instances.csv"');
    
    const headers = ['host', 'port', 'status', 'version', 'gpu_capable', 'vram_bytes', 'last_scanned', 'location', 'organization', 'models'];
    let csv = headers.join(',') + '\n';
    
    for (const row of results) {
      const csvRow = [
        row.host,
        row.port,
        row.status,
        row.ollama_version || '',
        row.gpu_capable || false,
        row.total_vram_bytes || 0,
        row.last_scanned || '',
        row.geographic_location || '',
        row.organization || '',
        (row.models || '').replace(/,/g, ';') // Replace commas in model list
      ];
      csv += csvRow.join(',') + '\n';
    }
    
    res.send(csv);
  }
}));

export default router;