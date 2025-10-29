import express from 'express';
import { createReadStream } from 'fs';
import StreamValues from 'stream-json/streamers/StreamValues';
import parser from 'stream-json';
import knex, { Knex } from 'knex';
import path from 'path';
import { logger } from './logger';

const app = express();
app.use(express.json({ limit: '100mb' }));

// Database connection
let db: Knex;

async function initializeDatabase() {
  const dbPath = process.env.DATABASE_URL?.replace('sqlite://', '') || 
                 path.join(process.cwd(), '../../data/ollama-discovery.db');
  
  db = knex({
    client: 'sqlite3',
    connection: { filename: dbPath },
    useNullAsDefault: true
  });
  
  await db.raw('SELECT 1');
  logger.info('JSON Processor database connected');
}

// Schema detection endpoint
app.post('/detect-schema', express.json(), async (req, res) => {
  try {
    const { filename, sampleSize = 10 } = req.body;
    const filePath = path.join(process.cwd(), '../..', 'uploads', filename);
    
    logger.info('Starting schema detection', { filename, sampleSize });
    
    const schema = await detectJSONSchema(filePath, sampleSize);
    
    res.json({
      success: true,
      schema,
      sampleSize: schema.samples.length
    });
  } catch (error) {
    logger.error('Schema detection failed:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// File processing endpoint
app.post('/process', express.json(), async (req, res) => {
  try {
    const { filename, jobId, extractFields, batchSize = 1000 } = req.body;
    const filePath = path.join(process.cwd(), '../..', 'uploads', filename);
    
    logger.info('Starting file processing', { 
      filename, 
      jobId, 
      extractFields, 
      batchSize 
    });
    
    const result = await processJSONFile(filePath, jobId, extractFields, batchSize);
    
    res.json({
      success: true,
      ...result
    });
  } catch (error) {
    logger.error('File processing failed:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'json-processor',
    timestamp: new Date().toISOString()
  });
});

interface SchemaField {
  name: string;
  type: string;
  examples: any[];
  frequency: number;
  isHostRelated?: boolean;
  isPortRelated?: boolean;
}

interface DetectedSchema {
  totalSamples: number;
  fields: SchemaField[];
  samples: any[];
  recommendedFields: string[];
}

async function detectJSONSchema(filePath: string, sampleSize: number): Promise<DetectedSchema> {
  return new Promise((resolve, reject) => {
    const samples: any[] = [];
    const fieldFrequency: Map<string, { type: Set<string>, examples: Set<any>, count: number }> = new Map();
    
    const stream = createReadStream(filePath)
      .pipe(parser())
      .pipe(StreamValues.withParser());
    
    let processedCount = 0;
    
    stream.on('data', (data) => {
      if (processedCount >= sampleSize) {
        stream.destroy();
        return;
      }
      
      const record = data.value;
      if (record && typeof record === 'object') {
        samples.push(record);
        processedCount++;
        
        // Analyze fields in this record
        analyzeRecordFields(record, fieldFrequency);
      }
    });
    
    stream.on('end', () => {
      const fields = Array.from(fieldFrequency.entries()).map(([name, info]) => ({
        name,
        type: Array.from(info.type).join(' | '),
        examples: Array.from(info.examples).slice(0, 3),
        frequency: info.count / samples.length,
        isHostRelated: isHostField(name),
        isPortRelated: isPortField(name)
      }));
      
      // Sort by frequency (most common first)
      fields.sort((a, b) => b.frequency - a.frequency);
      
      // Recommend default fields
      const recommendedFields = getRecommendedFields(fields);
      
      resolve({
        totalSamples: samples.length,
        fields,
        samples,
        recommendedFields
      });
    });
    
    stream.on('error', reject);
  });
}

function analyzeRecordFields(record: any, fieldFrequency: Map<string, any>, prefix = '') {
  for (const [key, value] of Object.entries(record)) {
    const fieldName = prefix ? `${prefix}.${key}` : key;
    
    if (!fieldFrequency.has(fieldName)) {
      fieldFrequency.set(fieldName, {
        type: new Set(),
        examples: new Set(),
        count: 0
      });
    }
    
    const field = fieldFrequency.get(fieldName)!;
    field.count++;
    field.type.add(typeof value);
    
    if (value !== null && value !== undefined) {
      field.examples.add(value);
    }
    
    // Recursively analyze nested objects (up to 2 levels deep)
    if (typeof value === 'object' && value !== null && !prefix.includes('.')) {
      analyzeRecordFields(value, fieldFrequency, fieldName);
    }
  }
}

function isHostField(fieldName: string): boolean {
  const hostPatterns = [
    /^ip$/i, /^host$/i, /^hostname$/i, /^address$/i, /^server$/i,
    /^target$/i, /^destination$/i, /ip_str$/i, /host_str$/i
  ];
  return hostPatterns.some(pattern => pattern.test(fieldName));
}

function isPortField(fieldName: string): boolean {
  const portPatterns = [
    /^port$/i, /^ports$/i, /^service_port$/i, /^target_port$/i
  ];
  return portPatterns.some(pattern => pattern.test(fieldName));
}

function getRecommendedFields(fields: SchemaField[]): string[] {
  const recommended: string[] = [];
  
  // Always try to include host/IP field
  const hostField = fields.find(f => f.isHostRelated && f.frequency > 0.1);
  if (hostField) {
    recommended.push(hostField.name);
  }
  
  // Always try to include port field
  const portField = fields.find(f => f.isPortRelated && f.frequency > 0.1);
  if (portField) {
    recommended.push(portField.name);
  }
  
  // Add other frequently occurring fields
  const otherFields = fields
    .filter(f => !f.isHostRelated && !f.isPortRelated && f.frequency > 0.5)
    .slice(0, 5)
    .map(f => f.name);
  
  recommended.push(...otherFields);
  
  return recommended;
}

interface ProcessingResult {
  totalRecords: number;
  processedRecords: number;
  duplicateRecords: number;
  errorRecords: number;
}

async function processJSONFile(
  filePath: string, 
  jobId: number, 
  extractFields?: string[], 
  batchSize: number = 1000
): Promise<ProcessingResult> {
  
  return new Promise((resolve, reject) => {
    let totalRecords = 0;
    let processedRecords = 0;
    let duplicateRecords = 0;
    let errorRecords = 0;
    let batch: any[] = [];
    
    const stream = createReadStream(filePath)
      .pipe(parser())
      .pipe(StreamValues.withParser());
    
    stream.on('data', async (data) => {
      totalRecords++;
      
      try {
        const record = data.value;
        const extractedData = extractFields ? 
          extractFieldsFromRecord(record, extractFields) : 
          extractDefaultFields(record);
        
        if (extractedData.host && extractedData.port) {
          batch.push({
            upload_job_id: jobId,
            host: extractedData.host,
            port: extractedData.port,
            protocol: extractedData.protocol || 'http',
            source_data: JSON.stringify(record),
            geographic_location: extractedData.location,
            organization: extractedData.organization,
            created_at: new Date().toISOString()
          });
          
          // Process batch when it reaches the batch size
          if (batch.length >= batchSize) {
            stream.pause();
            await processBatch(batch);
            processedRecords += batch.length;
            batch = [];
            stream.resume();
          }
        } else {
          errorRecords++;
        }
      } catch (error) {
        logger.warn('Record processing error:', { error: error.message, record: data.value });
        errorRecords++;
      }
    });
    
    stream.on('end', async () => {
      // Process remaining batch
      if (batch.length > 0) {
        await processBatch(batch);
        processedRecords += batch.length;
      }
      
      logger.info('File processing completed', {
        totalRecords,
        processedRecords,
        duplicateRecords,
        errorRecords
      });
      
      resolve({
        totalRecords,
        processedRecords,
        duplicateRecords,
        errorRecords
      });
    });
    
    stream.on('error', reject);
    
    // Process batch function
    async function processBatch(batchData: any[]) {
      try {
        await db('hosts').insert(batchData).onConflict(['host', 'port', 'upload_job_id']).ignore();
      } catch (error) {
        logger.error('Batch insert error:', error);
        throw error;
      }
    }
  });
}

function extractDefaultFields(record: any): any {
  // Common field mappings for network scan data
  const fieldMappings = [
    { target: 'host', sources: ['ip', 'host', 'ip_str', 'hostname', 'address', 'target'] },
    { target: 'port', sources: ['port', 'ports', 'service_port'] },
    { target: 'protocol', sources: ['protocol', 'service', 'transport'] },
    { target: 'location', sources: ['location', 'geo', 'country', 'city'] },
    { target: 'organization', sources: ['org', 'organization', 'isp', 'asn'] }
  ];
  
  const extracted: any = {};
  
  for (const mapping of fieldMappings) {
    const value = findFieldValue(record, mapping.sources);
    if (value !== null) {
      if (mapping.target === 'host') {
        extracted.host = convertToIPString(value);
      } else if (mapping.target === 'port') {
        extracted.port = Array.isArray(value) ? value[0] : parseInt(value);
      } else {
        extracted[mapping.target] = value;
      }
    }
  }
  
  return extracted;
}

function extractFieldsFromRecord(record: any, fields: string[]): any {
  const extracted: any = {};
  
  for (const field of fields) {
    const value = getNestedValue(record, field);
    if (value !== null && value !== undefined) {
      // Map to standard field names
      if (isHostField(field)) {
        extracted.host = convertToIPString(value);
      } else if (isPortField(field)) {
        extracted.port = Array.isArray(value) ? value[0] : parseInt(value);
      } else {
        extracted[field] = value;
      }
    }
  }
  
  return extracted;
}

function findFieldValue(obj: any, fieldNames: string[]): any {
  for (const name of fieldNames) {
    const value = getNestedValue(obj, name);
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

function getNestedValue(obj: any, path: string): any {
  return path.split('.').reduce((current, key) => {
    return current && current[key] !== undefined ? current[key] : null;
  }, obj);
}

function convertToIPString(value: any): string {
  if (typeof value === 'string') {
    return value;
  } else if (typeof value === 'number') {
    // Convert integer IP to string format
    return [
      (value >>> 24) & 255,
      (value >>> 16) & 255,
      (value >>> 8) & 255,
      value & 255
    ].join('.');
  }
  return String(value);
}

// Start server
const PORT = process.env.PORT || 4001;

initializeDatabase().then(() => {
  app.listen(PORT, () => {
    logger.info(`JSON Processor service running on port ${PORT}`);
  });
}).catch((error) => {
  logger.error('Failed to start JSON Processor:', error);
  process.exit(1);
});

export { app };