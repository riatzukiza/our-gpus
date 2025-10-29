import knex, { Knex } from 'knex';
import { config } from '../config';
import { logger } from '../utils/logger';
import fs from 'fs/promises';
import path from 'path';

let db: Knex | null = null;

export async function setupDatabase(): Promise<Knex> {
  if (db) {
    return db;
  }

  try {
    // Ensure data directory exists
    const dataDir = path.dirname(config.database.filename);
    await fs.mkdir(dataDir, { recursive: true });

    // Initialize Knex connection
    db = knex({
      client: 'sqlite3',
      connection: {
        filename: config.database.filename
      },
      useNullAsDefault: true,
      migrations: {
        tableName: 'knex_migrations',
        directory: path.join(__dirname, '../../migrations')
      }
    });

    // Test connection
    await db.raw('SELECT 1');
    logger.info('Database connection established', {
      filename: config.database.filename
    });

    // Initialize schema if needed
    await initializeSchema();
    
    return db;
  } catch (error) {
    logger.error('Database setup failed:', error);
    throw error;
  }
}

export async function initializeSchema(): Promise<void> {
  if (!db) {
    throw new Error('Database not initialized');
  }

  try {
    // Read and execute schema file
    const schemaPath = path.join(__dirname, '../../../database/schema.sql');
    const schemaSQL = await fs.readFile(schemaPath, 'utf-8');
    
    // Split by semicolon and execute each statement
    const statements = schemaSQL
      .split(';')
      .map(s => s.trim())
      .filter(s => s.length > 0);

    for (const statement of statements) {
      if (statement.toUpperCase().startsWith('PRAGMA')) {
        await db.raw(statement);
      } else if (statement.length > 0) {
        await db.raw(statement);
      }
    }

    logger.info('Database schema initialized successfully');
  } catch (error) {
    logger.error('Schema initialization failed:', error);
    throw error;
  }
}

export function getDatabase(): Knex {
  if (!db) {
    throw new Error('Database not initialized. Call setupDatabase() first.');
  }
  return db;
}

export async function closeDatabase(): Promise<void> {
  if (db) {
    await db.destroy();
    db = null;
    logger.info('Database connection closed');
  }
}