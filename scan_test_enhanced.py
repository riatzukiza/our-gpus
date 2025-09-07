#!/usr/bin/env python3
"""
Enhanced HTTP-based async Ollama scanner with GPU/system capability detection
Collects models, system info, VRAM usage, and version information
"""

import asyncio
import json
import urllib.request
import urllib.error
import csv
import os
import sys
import time
from datetime import datetime
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import threading
import queue
import socket
import re


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
    # Enhanced system capability fields
    ollama_version: str
    models_loaded: int
    total_vram_usage: int
    loaded_models_list: str
    largest_model_params: str
    gpu_capable: bool
    system_info: str


class HttpOllamaScanner:
    def __init__(self, max_concurrent: int = 100, timeout: int = 5, max_retries: int = 2):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        
    async def scan_host(self, host: str, port: str) -> ScanResult:
        """Scan a single host with rate limiting and retries"""
        async with self.semaphore:
            for attempt in range(self.max_retries):
                try:
                    result = await self._attempt_scan(host, port)
                    return result
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        return self._create_error_result(host, port, f"Max retries exceeded: {str(e)}")
                    await asyncio.sleep(0.5 * (2 ** attempt))
            
            return self._create_error_result(host, port, "Unexpected error")
            
    async def _attempt_scan(self, host: str, port: str) -> ScanResult:
        """Single scan attempt using HTTP request with enhanced info collection"""
        timestamp = datetime.now().isoformat()
        ollama_host_url = f"http://{host}:{port}"
        
        loop = asyncio.get_event_loop()
        
        try:
            # Collect comprehensive system information
            system_info = await loop.run_in_executor(
                self.executor, 
                self._collect_system_info, 
                host, port
            )
            
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
                    system_info=system_info['system_summary']
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
                    system_info=''
                )
                
        except Exception as e:
            return self._create_error_result(host, port, str(e))

    def _collect_system_info(self, host: str, port: str) -> Dict[str, Any]:
        """Collect comprehensive system information from Ollama APIs"""
        base_url = f"http://{host}:{port}"
        
        # Initialize result structure
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
            # 1. Get available models (/api/tags)
            tags_data = self._make_api_request(f"{base_url}/api/tags")
            if not tags_data['success']:
                result.update(tags_data)
                return result
            
            tags_json = json.loads(tags_data['data'])
            models = self._extract_models_from_json(tags_json)
            result['models_found'] = len(models)
            result['model_list'] = ', '.join(models) if models else 'No models'
            
            # 2. Get loaded models and VRAM usage (/api/ps)
            ps_data = self._make_api_request(f"{base_url}/api/ps")
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
                            
                            # Accumulate VRAM usage
                            vram = model.get('size_vram', 0)
                            if isinstance(vram, (int, float)):
                                total_vram += int(vram)
                            
                            # Track largest model parameters
                            if 'details' in model and isinstance(model['details'], dict):
                                params = model['details'].get('parameter_size', '')
                                if params and (not largest_params or self._compare_model_size(params, largest_params)):
                                    largest_params = params
            
            result['models_loaded'] = len(loaded_models)
            result['loaded_models_list'] = ', '.join(loaded_models) if loaded_models else 'None'
            result['total_vram_usage'] = total_vram
            result['largest_model_params'] = largest_params
            result['gpu_capable'] = total_vram > 0  # If any VRAM usage detected, GPU is available
            
            # 3. Get Ollama version (/api/version)
            version_data = self._make_api_request(f"{base_url}/api/version")
            if version_data['success']:
                version_json = json.loads(version_data['data'])
                result['version'] = version_json.get('version', 'unknown')
            
            # 4. Compile system summary
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

    def _make_api_request(self, url: str) -> Dict[str, Any]:
        """Make HTTP request to API endpoint"""
        try:
            request = urllib.request.Request(url)
            request.add_header('User-Agent', 'OllamaScanner/2.0')
            
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status == 200:
                    data = response.read().decode('utf-8')
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
                    
        except urllib.error.HTTPError as e:
            return {
                'success': False,
                'data': '',
                'error': f'HTTP {e.code}: {e.reason}',
                'status_code': e.code
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
            system_info=''
        )

    def cleanup(self):
        """Cleanup resources"""
        self.executor.shutdown(wait=True)


def load_hosts(filename: str) -> List[Tuple[str, str]]:
    """Load hosts from file"""
    hosts = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line:
                    host, port = line.split(':', 1)
                    hosts.append((host.strip(), port.strip()))
    except FileNotFoundError:
        print(f"Error: {filename} not found")
        sys.exit(1)
    return hosts


class BatchCSVWriter:
    """Efficient batch CSV writer with enhanced fields"""
    def __init__(self, filename: str, batch_size: int = 200):
        self.filename = filename
        self.batch_size = batch_size
        self.results_queue = queue.Queue()
        self.lock = threading.Lock()
        self.header_written = False
        
        self.fieldnames = [
            # Original fields
            'timestamp', 'host', 'port', 'ollama_host_url', 'success',
            'models_found', 'model_list', 'raw_output', 'error_message', 'return_code',
            # Enhanced system capability fields
            'ollama_version', 'models_loaded', 'total_vram_usage_bytes', 'loaded_models_list',
            'largest_model_params', 'gpu_capable', 'system_info'
        ]
        
    def add_result(self, result: ScanResult):
        """Add result to batch queue"""
        self.results_queue.put(result)
        
    def flush_batch(self):
        """Write all queued results to file"""
        results = []
        
        while not self.results_queue.empty():
            try:
                results.append(self.results_queue.get_nowait())
            except queue.Empty:
                break
        
        if not results:
            return len(results)
            
        with self.lock:
            mode = 'w' if not self.header_written else 'a'
            
            with open(self.filename, mode, newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.fieldnames)
                
                if not self.header_written:
                    writer.writeheader()
                    self.header_written = True
                
                for result in results:
                    writer.writerow({
                        'timestamp': result.timestamp,
                        'host': result.host,
                        'port': result.port,
                        'ollama_host_url': result.ollama_host_url,
                        'success': result.success,
                        'models_found': result.models_found,
                        'model_list': result.model_list,
                        'raw_output': result.raw_output,
                        'error_message': result.error_message,
                        'return_code': result.return_code,
                        'ollama_version': result.ollama_version,
                        'models_loaded': result.models_loaded,
                        'total_vram_usage_bytes': result.total_vram_usage,
                        'loaded_models_list': result.loaded_models_list,
                        'largest_model_params': result.largest_model_params,
                        'gpu_capable': result.gpu_capable,
                        'system_info': result.system_info
                    })
        
        return len(results)


def show_progress(total: int, completed: int, successful: int, failed: int, gpu_hosts: int = 0, rate: float = 0):
    """Display progress information with GPU stats"""
    percent = (completed / total) * 100 if total > 0 else 0
    bar_length = 35
    filled_length = int(bar_length * completed // total) if total > 0 else 0
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    
    rate_str = f" {rate:.1f}/s" if rate > 0 else ""
    gpu_str = f" GPU:{gpu_hosts}" if gpu_hosts > 0 else ""
    print(f'\r[{bar}] {percent:.1f}% ({completed}/{total}) ✓{successful} ✗{failed}{gpu_str}{rate_str}', 
          end='', flush=True)


async def main():
    hosts_file = 'test_hosts.txt'
    output_file = f'ollama_scan_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    # Configuration with higher defaults for HTTP scanning
    MAX_CONCURRENT = int(os.getenv('MAX_CONCURRENT', '100'))
    TIMEOUT = int(os.getenv('TIMEOUT', '5'))
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', '200'))
    
    print(f"Loading hosts from {hosts_file}...")
    hosts = load_hosts(hosts_file)
    
    if not hosts:
        print("No hosts found to scan")
        sys.exit(1)
        
    print(f"Found {len(hosts)} hosts to scan")
    print(f"Max concurrent: {MAX_CONCURRENT}, Timeout: {TIMEOUT}s, Batch size: {BATCH_SIZE}")
    print(f"Enhanced scanning: Models + GPU info + System capabilities")
    print(f"Results will be saved to: {output_file}")
    print()
    
    start_time = time.time()
    last_update = start_time
    completed = 0
    successful_scans = 0
    failed_scans = 0
    gpu_capable_hosts = 0
    
    scanner = HttpOllamaScanner(
        max_concurrent=MAX_CONCURRENT,
        timeout=TIMEOUT
    )
    
    csv_writer = BatchCSVWriter(output_file, BATCH_SIZE)
    
    try:
        tasks = []
        for host, port in hosts:
            task = scanner.scan_host(host, port)
            tasks.append(task)
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            csv_writer.add_result(result)
            completed += 1
            
            if result.success:
                successful_scans += 1
                if result.gpu_capable:
                    gpu_capable_hosts += 1
            else:
                failed_scans += 1
            
            # Update progress every 0.1 seconds or every batch
            current_time = time.time()
            if current_time - last_update >= 0.1 or completed % BATCH_SIZE == 0:
                elapsed = current_time - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                show_progress(len(hosts), completed, successful_scans, failed_scans, gpu_capable_hosts, rate)
                last_update = current_time
            
            if completed % BATCH_SIZE == 0:
                csv_writer.flush_batch()
        
        csv_writer.flush_batch()
        
    finally:
        scanner.cleanup()
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n\nScan complete in {duration:.2f} seconds!")
    print(f"Successful scans: {successful_scans}")
    print(f"Failed scans: {failed_scans}")
    print(f"GPU-capable hosts: {gpu_capable_hosts}")
    print(f"Average throughput: {len(hosts)/duration:.2f} hosts/second")
    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScan interrupted by user")
        sys.exit(1)