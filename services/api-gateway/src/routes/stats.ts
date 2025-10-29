import express from 'express';
import { asyncHandler } from '../middleware/errorHandler';
import { getDatabase } from '../database/setup';

const router = express.Router();

// Overall platform statistics
router.get('/', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const [
    totalHosts,
    totalInstances,
    activeInstances,
    gpuCapableHosts,
    totalModels,
    uniqueModels,
    recentScans,
    totalVramUsage
  ] = await Promise.all([
    // Total discovered hosts
    db('hosts').count('id as count').first(),
    
    // Total Ollama instances found
    db('ollama_instances').count('id as count').first(),
    
    // Active instances
    db('ollama_instances').where('status', 'active').count('id as count').first(),
    
    // GPU-capable hosts
    db('ollama_instances').where('gpu_capable', true).count('id as count').first(),
    
    // Total model installations
    db('models').count('id as count').first(),
    
    // Unique model types
    db('models').countDistinct('name as count').first(),
    
    // Recent scans (last 24 hours)
    db('scan_jobs')
      .where('created_at', '>', new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
      .count('id as count')
      .first(),
    
    // Total VRAM usage
    db('ollama_instances')
      .sum('total_vram_bytes as total')
      .first()
  ]);

  res.json({
    summary: {
      total_hosts: totalHosts?.count || 0,
      total_instances: totalInstances?.count || 0,
      active_instances: activeInstances?.count || 0,
      gpu_capable_hosts: gpuCapableHosts?.count || 0,
      total_models: totalModels?.count || 0,
      unique_models: uniqueModels?.count || 0,
      recent_scans_24h: recentScans?.count || 0,
      total_vram_gb: Math.round((totalVramUsage?.total || 0) / (1024 * 1024 * 1024))
    }
  });
}));

// Version distribution
router.get('/versions', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const versions = await db('ollama_instances')
    .select('ollama_version')
    .count('* as count')
    .whereNotNull('ollama_version')
    .where('ollama_version', '!=', '')
    .groupBy('ollama_version')
    .orderBy('count', 'desc')
    .limit(20);

  res.json({
    versions: versions.map(v => ({
      version: v.ollama_version,
      count: v.count
    }))
  });
}));

// Model popularity
router.get('/models', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const limit = parseInt(req.query.limit as string) || 50;

  const models = await db('models as m')
    .join('ollama_instances as oi', 'm.ollama_instance_id', 'oi.id')
    .select('m.name', 'm.family', 'm.parameter_size')
    .count('m.id as installations')
    .countDistinct('oi.host_id as unique_hosts')
    .where('oi.status', 'active')
    .groupBy('m.name', 'm.family', 'm.parameter_size')
    .orderBy('installations', 'desc')
    .limit(limit);

  res.json({
    popular_models: models
  });
}));

// Geographic distribution
router.get('/geography', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const locations = await db('hosts as h')
    .join('ollama_instances as oi', 'h.id', 'oi.host_id')
    .select('h.geographic_location')
    .count('oi.id as instance_count')
    .sum(db.raw('CASE WHEN oi.gpu_capable = 1 THEN 1 ELSE 0 END as gpu_count'))
    .whereNotNull('h.geographic_location')
    .where('h.geographic_location', '!=', '')
    .where('oi.status', 'active')
    .groupBy('h.geographic_location')
    .orderBy('instance_count', 'desc')
    .limit(50);

  res.json({
    geographic_distribution: locations.map(loc => ({
      location: loc.geographic_location,
      instances: loc.instance_count,
      gpu_hosts: loc.gpu_count
    }))
  });
}));

// Organization distribution
router.get('/organizations', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const orgs = await db('hosts as h')
    .join('ollama_instances as oi', 'h.id', 'oi.host_id')
    .select('h.organization')
    .count('oi.id as instance_count')
    .sum(db.raw('CASE WHEN oi.gpu_capable = 1 THEN 1 ELSE 0 END as gpu_count'))
    .avg('oi.total_vram_bytes as avg_vram')
    .whereNotNull('h.organization')
    .where('h.organization', '!=', '')
    .where('oi.status', 'active')
    .groupBy('h.organization')
    .orderBy('instance_count', 'desc')
    .limit(30);

  res.json({
    top_organizations: orgs.map(org => ({
      organization: org.organization,
      instances: org.instance_count,
      gpu_hosts: org.gpu_count,
      avg_vram_gb: Math.round((org.avg_vram || 0) / (1024 * 1024 * 1024))
    }))
  });
}));

// Scanning activity timeline
router.get('/timeline', asyncHandler(async (req, res) => {
  const db = getDatabase();
  const days = parseInt(req.query.days as string) || 7;
  const startDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000);

  const timeline = await db('scan_jobs')
    .select(
      db.raw('DATE(created_at) as date'),
      db.raw('COUNT(*) as scans'),
      db.raw('SUM(successful_scans) as successful'),
      db.raw('SUM(failed_scans) as failed'),
      db.raw('SUM(active_instances_found) as instances_found'),
      db.raw('SUM(gpu_capable_found) as gpu_hosts_found')
    )
    .where('created_at', '>=', startDate.toISOString())
    .groupBy(db.raw('DATE(created_at)'))
    .orderBy('date');

  res.json({
    timeline: timeline,
    period_days: days
  });
}));

// System health metrics
router.get('/health', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const [
    failedScansRecent,
    avgScanDuration,
    lastSuccessfulScan,
    oldestUnscaneed
  ] = await Promise.all([
    // Failed scans in last 24h
    db('scan_jobs')
      .where('status', 'failed')
      .where('created_at', '>', new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
      .count('id as count')
      .first(),
    
    // Average scan duration for completed jobs
    db('scan_jobs')
      .where('status', 'completed')
      .avg('duration_seconds as avg_duration')
      .first(),
    
    // Last successful scan
    db('scan_jobs')
      .where('status', 'completed')
      .orderBy('completed_at', 'desc')
      .select('completed_at', 'name')
      .first(),
    
    // Oldest host that hasn't been scanned
    db('hosts as h')
      .leftJoin('ollama_instances as oi', 'h.id', 'oi.host_id')
      .whereNull('oi.id')
      .orderBy('h.created_at')
      .select('h.created_at', 'h.host')
      .first()
  ]);

  res.json({
    health_metrics: {
      recent_failures: failedScansRecent?.count || 0,
      avg_scan_duration_seconds: Math.round(avgScanDuration?.avg_duration || 0),
      last_successful_scan: lastSuccessfulScan,
      oldest_unscanned: oldestUnscaneed
    }
  });
}));

// Real-time statistics for dashboard
router.get('/realtime', asyncHandler(async (req, res) => {
  const db = getDatabase();

  const [
    runningScanJobs,
    recentlyActive,
    topModelsToday,
    newInstancesToday
  ] = await Promise.all([
    // Currently running scan jobs
    db('scan_jobs')
      .where('status', 'running')
      .select('id', 'name', 'progress', 'started_at', 'host_count'),
    
    // Recently active instances (last scanned within 1 hour)
    db('ollama_instances')
      .where('last_scanned', '>', new Date(Date.now() - 60 * 60 * 1000).toISOString())
      .where('status', 'active')
      .count('id as count')
      .first(),
    
    // Top 5 models discovered today
    db('models as m')
      .join('ollama_instances as oi', 'm.ollama_instance_id', 'oi.id')
      .where('m.created_at', '>', new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
      .select('m.name')
      .count('m.id as count')
      .groupBy('m.name')
      .orderBy('count', 'desc')
      .limit(5),
    
    // New instances discovered today
    db('ollama_instances')
      .where('created_at', '>', new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
      .count('id as count')
      .first()
  ]);

  res.json({
    realtime: {
      running_scans: runningScanJobs,
      recently_active_instances: recentlyActive?.count || 0,
      top_models_today: topModelsToday,
      new_instances_today: newInstancesToday?.count || 0,
      timestamp: new Date().toISOString()
    }
  });
}));

export default router;