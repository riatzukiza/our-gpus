#!/usr/bin/env python3
"""
FastAPI-based Ollama Scanner Service
Enhanced HTTP-based async Ollama scanner with GPU/system capability detection
"""

import asyncio
import json
import sqlite3
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    timestamp: str
    host: str
    port: str
    ollama_host_url: str
    success: bool
    models_found: int
    model_list: str
    raw_output: str
    error_message: str
    return_code: int
    ollama_version: str
    models_loaded: int
    total_vram_usage: int
    loaded_models_list: str
    largest_model_params: str
    gpu_capable: bool
    system_info: str
    scan_duration_ms: int


class ScanRequest(BaseModel):
    hosts: List[Dict[str, Any]]
    scan_job_id: int
    max_concurrent: int = 100
    timeout: int = 5
    max_retries: int = 2


class ScanJobStatus(BaseModel):
    job_id: int
    status: str
    progress: int
    successful_scans: int
    failed_scans: int
    active_instances_found: int
    gpu_capable_found: int


class HttpOllamaScanner:
    def __init__(self, max_concurrent: int = 100, timeout: int = 5, max_retries: int = 2):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    async def scan_host(self, host: str, port: str) -> ScanResult:
        """Scan a single host with rate limiting and retries"""
        async with self.semaphore:
            start_time = time.time()
            
            for attempt in range(self.max_retries):
                try:
                    result = await self._attempt_scan(host, port)
                    result.scan_duration_ms = int((time.time() - start_time) * 1000)
                    return result
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        result = self._create_error_result(host, port, f"Max retries exceeded: {str(e)}")
                        result.scan_duration_ms = int((time.time() - start_time) * 1000)
                        return result
                    await asyncio.sleep(0.5 * (2 ** attempt))
            
            return self._create_error_result(host, port, "Unexpected error")
            
    async def _attempt_scan(self, host: str, port: str) -> ScanResult:
        """Single scan attempt using HTTP request with enhanced info collection"""
        timestamp = datetime.now().isoformat()
        ollama_host_url = f"http://{host}:{port}"
        
        try:
            system_info = await self._collect_system_info(host, port)
            
            if system_info['success']:
                return ScanResult(
                    timestamp=timestamp,
                    host=host,
                    port=port,
                    ollama_host_url=ollama_host_url,
                    success=True,
                    models_found=system_info['models_found'],
                    model_list=system_info['model_list'],
                    raw_output=system_info['raw_data'],
                    error_message='',
                    return_code=0,
                    ollama_version=system_info['version'],
                    models_loaded=system_info['models_loaded'],
                    total_vram_usage=system_info['total_vram_usage'],
                    loaded_models_list=system_info['loaded_models_list'],
                    largest_model_params=system_info['largest_model_params'],
                    gpu_capable=system_info['gpu_capable'],
                    system_info=system_info['system_summary'],
                    scan_duration_ms=0
                )
            else:
                return ScanResult(
                    timestamp=timestamp,
                    host=host,
                    port=port,
                    ollama_host_url=ollama_host_url,
                    success=False,
                    models_found=0,
                    model_list='',
                    raw_output='',
                    error_message=system_info['error'],
                    return_code=system_info['status_code'],
                    ollama_version='',
                    models_loaded=0,
                    total_vram_usage=0,
                    loaded_models_list='',
                    largest_model_params='',
                    gpu_capable=False,
                    system_info='',
                    scan_duration_ms=0
                )
                
        except Exception as e:
            return self._create_error_result(host, port, str(e))

    async def _collect_system_info(self, host: str, port: str) -> Dict[str, Any]:
        """Collect comprehensive system information from Ollama APIs"""
        base_url = f"http://{host}:{port}"
        
        result = {
            'success': False,
            'models_found': 0,
            'model_list': '',
            'models_loaded': 0,
            'loaded_models_list': '',
            'total_vram_usage': 0,
            'largest_model_params': '',
            'gpu_capable': False,
            'version': '',
            'raw_data': '',
            'system_summary': '',
            'error': '',
            'status_code': -1
        }
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                # Get available models (/api/tags)
                tags_data = await self._make_api_request(session, f"{base_url}/api/tags")
                if not tags_data['success']:
                    result.update(tags_data)
                    return result
                
                tags_json = json.loads(tags_data['data'])
                models = self._extract_models_from_json(tags_json)
                result['models_found'] = len(models)
                result['model_list'] = ', '.join(models) if models else 'No models'
                
                # Get loaded models and VRAM usage (/api/ps)
                ps_data = await self._make_api_request(session, f"{base_url}/api/ps")
                loaded_models = []
                total_vram = 0
                largest_params = ''
                
                if ps_data['success']:
                    ps_json = json.loads(ps_data['data'])
                    if 'models' in ps_json and isinstance(ps_json['models'], list):
                        for model in ps_json['models']:
                            if isinstance(model, dict):
                                model_name = model.get('name', 'unknown')
                                loaded_models.append(model_name)
                                
                                vram = model.get('size_vram', 0)
                                if isinstance(vram, (int, float)):
                                    total_vram += int(vram)
                                
                                if 'details' in model and isinstance(model['details'], dict):
                                    params = model['details'].get('parameter_size', '')
                                    if params and (not largest_params or self._compare_model_size(params, largest_params)):
                                        largest_params = params
                
                result['models_loaded'] = len(loaded_models)
                result['loaded_models_list'] = ', '.join(loaded_models) if loaded_models else 'None'
                result['total_vram_usage'] = total_vram
                result['largest_model_params'] = largest_params
                result['gpu_capable'] = total_vram > 0
                
                # Get Ollama version (/api/version)
                version_data = await self._make_api_request(session, f"{base_url}/api/version")
                if version_data['success']:
                    version_json = json.loads(version_data['data'])
                    result['version'] = version_json.get('version', 'unknown')
                
                # Compile system summary
                system_parts = []
                if result['version']:
                    system_parts.append(f"v{result['version']}")
                if result['gpu_capable']:
                    system_parts.append(f"GPU:{result['total_vram_usage']//1024//1024}MB")
                if result['models_loaded'] > 0:
                    system_parts.append(f"Loaded:{result['models_loaded']}")
                if largest_params:
                    system_parts.append(f"Max:{largest_params}")
                
                result['system_summary'] = ' | '.join(system_parts)
                
                # Combine raw data
                raw_parts = [tags_data['data']]
                if ps_data['success']:
                    raw_parts.append(ps_data['data'])
                if version_data['success']:
                    raw_parts.append(version_data['data'])
                
                result['raw_data'] = ' | '.join(raw_parts)
                result['success'] = True
                result['status_code'] = 200
                
        except Exception as e:
            result['error'] = str(e)
            result['status_code'] = -1
        
        return result

    async def _make_api_request(self, session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
        """Make HTTP request to API endpoint"""
        try:
            headers = {'User-Agent': 'OllamaScanner/2.0'}
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.text()
                    return {
                        'success': True,
                        'data': data,
                        'status_code': 200
                    }
                else:
                    return {
                        'success': False,
                        'data': '',
                        'error': f'HTTP {response.status}',
                        'status_code': response.status
                    }
        except Exception as e:
            return {
                'success': False,
                'data': '',
                'error': str(e),
                'status_code': -1
            }

    def _extract_models_from_json(self, data: dict) -> List[str]:
        """Extract model names from JSON response"""
        models = []
        if isinstance(data, dict) and 'models' in data:
            if isinstance(data['models'], list):
                for model in data['models']:
                    if isinstance(model, dict) and 'name' in model:
                        models.append(model['name'])
        return models

    def _compare_model_size(self, size1: str, size2: str) -> bool:
        """Compare model parameter sizes (returns True if size1 > size2)"""
        def parse_size(size_str):
            if not size_str:
                return 0
            import re
            match = re.search(r'([0-9.]+)\s*([KMGTB]?)', size_str.upper())
            if not match:
                return 0
            
            value = float(match.group(1))
            unit = match.group(2)
            
            multipliers = {'K': 1e3, 'M': 1e6, 'G': 1e9, 'T': 1e12, 'B': 1e9}
            return value * multipliers.get(unit, 1)
        
        return parse_size(size1) > parse_size(size2)

    def _create_error_result(self, host: str, port: str, error: str) -> ScanResult:
        """Create error result with all required fields"""
        return ScanResult(
            timestamp=datetime.now().isoformat(),
            host=host,
            port=port,
            ollama_host_url=f"http://{host}:{port}",
            success=False,
            models_found=0,
            model_list='',
            raw_output='',
            error_message=error,
            return_code=-1,
            ollama_version='',
            models_loaded=0,
            total_vram_usage=0,
            loaded_models_list='',
            largest_model_params='',
            gpu_capable=False,
            system_info='',
            scan_duration_ms=0
        )


# Global scanner instance and database connection
scanner = None
db_connection = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global scanner, db_connection
    scanner = HttpOllamaScanner()
    
    # Initialize database connection
    db_path = "/app/data/ollama-discovery.db"
    db_connection = sqlite3.connect(db_path, check_same_thread=False)
    logger.info("Ollama Scanner service started")
    
    yield
    
    # Shutdown
    if db_connection:
        db_connection.close()
    logger.info("Ollama Scanner service stopped")


app = FastAPI(
    title="Ollama Scanner Service",
    description="HTTP-based async Ollama scanner with GPU/system capability detection",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "ollama-scanner",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/scan")
async def start_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """Start a new scan job"""
    global scanner
    
    if not scanner:
        raise HTTPException(status_code=500, detail="Scanner not initialized")
    
    # Update scanner configuration
    scanner.max_concurrent = request.max_concurrent
    scanner.timeout = request.timeout
    scanner.max_retries = request.max_retries
    scanner.semaphore = asyncio.Semaphore(request.max_concurrent)
    
    # Update scan job status to 'running'
    if db_connection:
        cursor = db_connection.cursor()
        cursor.execute("""
            UPDATE scan_jobs 
            SET status = 'running', started_at = ?, updated_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), datetime.now().isoformat(), request.scan_job_id))
        db_connection.commit()
    
    # Start background scanning
    background_tasks.add_task(
        perform_scan,
        request.hosts,
        request.scan_job_id
    )
    
    return {
        "success": True,
        "message": f"Scan started for {len(request.hosts)} hosts",
        "job_id": request.scan_job_id
    }


async def perform_scan(hosts: List[Dict[str, Any]], job_id: int):
    """Perform the actual scanning operation"""
    global scanner
    
    logger.info(f"Starting scan job {job_id} with {len(hosts)} hosts")
    
    successful_scans = 0
    failed_scans = 0
    active_instances = 0
    gpu_capable_hosts = 0
    
    try:
        # Create scan tasks
        if not scanner:
            raise Exception("Scanner not initialized")
            
        tasks = []
        for host_data in hosts:
            task = scanner.scan_host(host_data['host'], str(host_data['port']))
            tasks.append((task, host_data))
        
        # Process results as they complete
        for i, (coro, host_data) in enumerate(tasks):
            result = await coro
            
            # Update counters
            if result.success:
                successful_scans += 1
                active_instances += 1
                if result.gpu_capable:
                    gpu_capable_hosts += 1
            else:
                failed_scans += 1
            
            # Store results in database
            await store_scan_result(result, host_data['host_id'])
            
            # Update progress
            if db_connection:
                progress = int(((i + 1) / len(hosts)) * 100)
                cursor = db_connection.cursor()
                cursor.execute("""
                    UPDATE scan_jobs 
                    SET progress = ?, successful_scans = ?, failed_scans = ?, 
                        active_instances_found = ?, gpu_capable_found = ?, 
                        updated_at = ?
                    WHERE id = ?
                """, (progress, successful_scans, failed_scans, active_instances, 
                      gpu_capable_hosts, datetime.now().isoformat(), job_id))
                db_connection.commit()
        
        # Mark job as completed
        if db_connection:
            cursor = db_connection.cursor()
            cursor.execute("""
                UPDATE scan_jobs 
                SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), datetime.now().isoformat(), job_id))
            db_connection.commit()
        
        logger.info(f"Scan job {job_id} completed: {successful_scans} successful, {failed_scans} failed")
        
    except Exception as e:
        logger.error(f"Scan job {job_id} failed: {e}")
        
        # Mark job as failed
        if db_connection:
            cursor = db_connection.cursor()
            cursor.execute("""
                UPDATE scan_jobs 
                SET status = 'failed', updated_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), job_id))
            db_connection.commit()


async def store_scan_result(result: ScanResult, host_id: int):
    """Store scan result in database"""
    if not db_connection:
        return
        
    cursor = db_connection.cursor()
    
    # Insert or update ollama_instance
    if result.success:
        cursor.execute("""
            INSERT OR REPLACE INTO ollama_instances 
            (host_id, ollama_url, status, last_scanned, response_time_ms,
             ollama_version, api_version, gpu_capable, total_vram_bytes,
             system_info, scan_duration_ms, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            host_id, result.ollama_host_url, 'active', result.timestamp, 
            result.scan_duration_ms, result.ollama_version, '', 
            result.gpu_capable, result.total_vram_usage, result.system_info,
            result.scan_duration_ms, datetime.now().isoformat()
        ))
        
        instance_id = cursor.lastrowid
        
        # Store models if any found
        if result.models_found > 0 and result.model_list != 'No models':
            models = result.model_list.split(', ')
            for model in models:
                cursor.execute("""
                    INSERT OR REPLACE INTO models 
                    (ollama_instance_id, name, created_at)
                    VALUES (?, ?, ?)
                """, (instance_id, model, datetime.now().isoformat()))
        
        # Store loaded models
        if result.models_loaded > 0 and result.loaded_models_list != 'None':
            loaded_models = result.loaded_models_list.split(', ')
            for model in loaded_models:
                cursor.execute("""
                    INSERT OR REPLACE INTO loaded_models 
                    (ollama_instance_id, model_name, vram_usage_bytes, loaded_at)
                    VALUES (?, ?, ?, ?)
                """, (instance_id, model, result.total_vram_usage // len(loaded_models), 
                      datetime.now().isoformat()))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO ollama_instances 
            (host_id, ollama_url, status, last_scanned, error_message,
             scan_duration_ms, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            host_id, result.ollama_host_url, 'inactive', result.timestamp,
            result.error_message, result.scan_duration_ms, datetime.now().isoformat()
        ))
    
    db_connection.commit()


@app.get("/scan/{job_id}/status")
async def get_scan_status(job_id: int) -> ScanJobStatus:
    """Get status of a scan job"""
    if not db_connection:
        raise HTTPException(status_code=500, detail="Database not connected")
        
    cursor = db_connection.cursor()
    cursor.execute("""
        SELECT status, progress, successful_scans, failed_scans, 
               active_instances_found, gpu_capable_found
        FROM scan_jobs WHERE id = ?
    """, (job_id,))
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return ScanJobStatus(
        job_id=job_id,
        status=row[0],
        progress=row[1],
        successful_scans=row[2],
        failed_scans=row[3],
        active_instances_found=row[4],
        gpu_capable_found=row[5]
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=4002,
        reload=True,
        log_level="info"
    )