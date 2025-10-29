import dotenv from 'dotenv';
import path from 'path';

dotenv.config();

export const config = {
  port: parseInt(process.env.PORT || '4000', 10),
  environment: process.env.NODE_ENV || 'development',
  
  database: {
    client: 'sqlite3',
    filename: process.env.DATABASE_URL?.replace('sqlite://', '') || path.join(process.cwd(), 'data', 'ollama-discovery.db'),
    useNullAsDefault: true,
    migrations: {
      directory: path.join(__dirname, '../migrations')
    }
  },
  
  redis: {
    url: process.env.REDIS_URL || 'redis://localhost:6379'
  },
  
  services: {
    jsonProcessor: {
      url: process.env.JSON_PROCESSOR_URL || 'http://localhost:4001'
    },
    ollamaScanner: {
      url: process.env.OLLAMA_SCANNER_URL || 'http://localhost:4002'
    }
  },
  
  frontend: {
    url: process.env.FRONTEND_URL || 'http://localhost:3000'
  },
  
  upload: {
    maxFileSizeGB: parseInt(process.env.MAX_FILE_SIZE_GB || '10', 10),
    allowedTypes: ['application/json', 'text/plain'],
    uploadDir: path.join(process.cwd(), 'uploads')
  },
  
  scanning: {
    defaultMaxConcurrent: parseInt(process.env.DEFAULT_MAX_CONCURRENT || '100', 10),
    defaultTimeout: parseInt(process.env.DEFAULT_TIMEOUT || '5', 10),
    maxRetries: parseInt(process.env.MAX_RETRIES || '2', 10)
  },
  
  logging: {
    level: process.env.LOG_LEVEL || 'info',
    format: process.env.LOG_FORMAT || 'json'
  }
};