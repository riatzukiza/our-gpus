# Ollama Scrape Tool

High-performance Python tools for discovering Ollama instances across networks and analyzing their capabilities, including GPU usage, model deployments, and system configurations.

## 📊 Scripts Overview

### Core Scripts:
1. **`extract_hosts.py`** - Parses JSON scan data to extract host/IP and port information
2. **`scan_ollama_hosts.py`** - *[ORIGINAL]* Sequential Ollama scanner (~1 host/second)

### High-Performance Scanners:
3. **`scan_ollama_hosts_async.py`** - Async subprocess-based scanner (50-200 hosts/second)
4. **`scan_ollama_hosts_http.py`** - *[RECOMMENDED]* HTTP-based scanner with GPU detection (200-1000+ hosts/second)

### Analysis Tools:
5. **`analyze_gpu_capabilities.py`** - Analyzes scan results for GPU capabilities and system insights

## 🛠 Prerequisites

### All Scripts:
- Python 3.7+ (uses asyncio, dataclasses)
- JSON scan data file (e.g., from network scanning tools like masscan, nmap, etc.)

### For subprocess-based scanners (`scan_ollama_hosts.py`, `scan_ollama_hosts_async.py`):
- [Ollama CLI](https://ollama.ai) installed and accessible in PATH

### For HTTP-based scanner (`scan_ollama_hosts_http.py`):
- **No external dependencies** - uses only Python standard library
- **Fastest performance** - direct HTTP API calls to Ollama instances

## Installation

1. Clone this repository:
   ```bash
   git clone git@github.com:Latitudes-Dev/ollama-scrape.git
   cd ollama-scrape
   ```

2. Make scripts executable:
   ```bash
   chmod +x *.py
   ```

## Usage

### Step 1: Extract Host Information

Extract host and port information from your JSON scan data:

```bash
python3 extract_hosts.py <json_file>
```

**Example:**
```bash
python3 extract_hosts.py f07vbw0rg.json
```

**What it does:**
- Parses each line of the JSON file as a separate JSON object
- Extracts host/IP addresses (converts integer IPs to string format if needed)
- Extracts port information (defaults to 80 for HTTP, 443 for HTTPS)
- Outputs results to console and saves to `hosts_and_ports.txt`

**Expected JSON format:**
```json
{"host": "192.168.1.1", "port": 11434}
{"ip": 3232235777, "port": 11434}
```

### Step 2: Scan for Ollama Instances

Choose the scanner that best fits your needs:

#### 🚀 **Recommended: HTTP-based Scanner (Fastest)**
```bash
python3 scan_ollama_hosts_http.py
```
- **Speed**: 200-1000+ hosts/second
- **Features**: GPU detection, VRAM usage, system capabilities
- **Requirements**: No external dependencies
- **Best for**: Large-scale scanning, comprehensive analysis

#### ⚡ **Async Scanner (Fast)**
```bash
python3 scan_ollama_hosts_async.py
```
- **Speed**: 50-200 hosts/second  
- **Features**: Basic model discovery
- **Requirements**: Ollama CLI installed
- **Best for**: Medium-scale scanning

#### 🐌 **Original Scanner (Slow but Reliable)**
```bash
python3 scan_ollama_hosts.py
```
- **Speed**: ~1 host/second
- **Features**: Basic model discovery
- **Requirements**: Ollama CLI installed
- **Best for**: Small-scale testing, debugging

#### Performance Configuration

All scanners support environment variable configuration:

```bash
# Configure concurrent connections (default varies by scanner)
MAX_CONCURRENT=50 python3 scan_ollama_hosts_http.py

# Configure timeout (default varies by scanner)
TIMEOUT=10 python3 scan_ollama_hosts_http.py

# Configure batch size for CSV writes
BATCH_SIZE=100 python3 scan_ollama_hosts_http.py
```

### 📁 CSV Output Fields

#### Basic Fields (All Scanners):
| Field | Description |
|-------|-------------|
| timestamp | When the scan occurred |
| host | Target host/IP address |
| port | Target port |
| ollama_host_url | Full URL used for Ollama connection |
| success | Boolean indicating if scan succeeded |
| models_found | Number of models discovered |
| model_list | Comma-separated list of model names |
| raw_output | Raw output from scanner |
| error_message | Error message if scan failed |
| return_code | Process return code |

#### Enhanced Fields (HTTP Scanner Only):
| Field | Description |
|-------|-------------|
| ollama_version | Ollama version (e.g., "0.5.7", "0.11.7") |
| models_loaded | Number of currently loaded models |
| total_vram_usage_bytes | GPU memory usage in bytes |
| loaded_models_list | Names of currently loaded models |
| largest_model_params | Parameter count of largest model |
| gpu_capable | Boolean indicating GPU availability |
| system_info | Condensed system summary |

### 🔍 Analyzing Results

Use the analysis script to get insights from enhanced scans:

```bash
python3 analyze_gpu_capabilities.py ollama_scan_results_20241205_143022.csv
```

**Sample Analysis Output:**
```
🔍 OLLAMA SYSTEM CAPABILITY ANALYSIS
==================================================
📊 SCAN SUMMARY:
  Total hosts scanned: 3,625
  Successful scans: 847
  Failed scans: 2,778
  Success rate: 23.4%

🖥️  COMPUTE CAPABILITIES:
  GPU-capable hosts: 234
  CPU-only hosts: 613
  GPU adoption rate: 27.6%
  Total VRAM usage: 2,847,392,768 bytes (2,714 MB)

🤖 MODEL DEPLOYMENT:
  Hosts with loaded models: 156
  Total models loaded: 342

📦 OLLAMA VERSIONS:
  v0.5.7: 423 hosts (49.9%)
  v0.11.7: 312 hosts (36.8%)
  v0.8.2: 89 hosts (10.5%)

🏷️  POPULAR MODEL FAMILIES:
  llama3.1: 234 deployments (18.2%)
  llama3.2: 187 deployments (14.5%)
  qwen2.5: 156 deployments (12.1%)
```

## 🎯 Example Workflows

### Quick Start (Recommended):
```bash
# 1. Extract hosts from scan data
python3 extract_hosts.py scan_results.json

# 2. High-performance scan with GPU detection
python3 scan_ollama_hosts_http.py

# 3. Analyze results
python3 analyze_gpu_capabilities.py ollama_scan_results_20241205_143022.csv
```

### Large-Scale Network Analysis:
```bash
# High-concurrency scanning for large networks
MAX_CONCURRENT=200 TIMEOUT=3 python3 scan_ollama_hosts_http.py

# Sample Output:
# Loading hosts from hosts_and_ports.txt...
# Found 10,247 hosts to scan
# Max concurrent: 200, Timeout: 3s, Batch size: 200
# Enhanced scanning: Models + GPU info + System capabilities
# 
# [████████████████████████████████████] 100.0% (10247/10247) ✓2847 ✗7400 GPU:234 847.2/s
#
# Scan complete in 12.11 seconds!
# Successful scans: 2,847
# Failed scans: 7,400
# GPU-capable hosts: 234
# Average throughput: 847.2 hosts/second
```

### Performance Comparison:
```bash
# Test same 100 hosts with different scanners:

time python3 scan_ollama_hosts.py          # ~100 seconds (1/sec)
time python3 scan_ollama_hosts_async.py    # ~2-5 seconds (20-50/sec)  
time python3 scan_ollama_hosts_http.py     # ~0.1-1 seconds (100-1000/sec)
```

## 🚨 Troubleshooting

### Common Issues

1. **`ollama command not found`** (subprocess scanners only)
   - Install Ollama CLI from https://ollama.ai
   - Ensure it's in your PATH
   - **Solution**: Use HTTP scanner instead (no CLI required)

2. **Connection timeouts**
   - Adjust timeout: `TIMEOUT=10 python3 scan_ollama_hosts_http.py`
   - Many hosts may not be running Ollama or may be behind firewalls

3. **Too many concurrent connections**
   - Reduce concurrency: `MAX_CONCURRENT=20 python3 scan_ollama_hosts_http.py`
   - Some networks may rate-limit connections

4. **Permission denied**
   - Make scripts executable: `chmod +x *.py`

5. **JSON parsing errors**
   - Check that your JSON file has one JSON object per line
   - Invalid JSON lines are skipped with error messages

6. **Memory issues with large scans**
   - Reduce batch size: `BATCH_SIZE=50 python3 scan_ollama_hosts_http.py`
   - Results are written in batches to prevent memory buildup

### Performance Tuning

| Scanner | Default Concurrent | Recommended Range | Max Tested |
|---------|-------------------|------------------|------------|
| HTTP-based | 100 | 50-200 | 500+ |
| Async subprocess | 20 | 10-50 | 100 |
| Original | 1 | 1 | 1 |

```bash
# Conservative (stable)
MAX_CONCURRENT=20 TIMEOUT=10 python3 scan_ollama_hosts_http.py

# Aggressive (fast)
MAX_CONCURRENT=200 TIMEOUT=3 python3 scan_ollama_hosts_http.py

# Custom configuration
MAX_CONCURRENT=100 TIMEOUT=5 BATCH_SIZE=200 python3 scan_ollama_hosts_http.py
```

## 🛡️ Security & Ethics

**⚠️ Important**: This tool is for legitimate security research and authorized testing only. 

### Ethical Usage:
- ✅ **Authorized testing** of your own infrastructure
- ✅ **Bug bounty programs** with explicit scope
- ✅ **Security research** with proper disclosure
- ❌ **Unauthorized scanning** of third-party networks
- ❌ **Malicious reconnaissance** or attacks

### Rate Limiting:
- The tools include built-in rate limiting to be respectful
- Adjust `MAX_CONCURRENT` based on your authorization scope
- Consider network impact when choosing concurrency levels

### Responsible Disclosure:
If you discover vulnerabilities through authorized scanning:
1. Document findings responsibly
2. Follow coordinated disclosure practices  
3. Notify affected parties through appropriate channels
4. Allow reasonable time for remediation

**Always ensure you have explicit permission before scanning networks or hosts you don't own.**

---

## 📊 Feature Comparison

| Feature | Original | Async | HTTP |
|---------|----------|--------|------|
| **Speed** | 1/sec | 50-200/sec | 200-1000+/sec |
| **Dependencies** | Ollama CLI | Ollama CLI | None |
| **GPU Detection** | ❌ | ❌ | ✅ |
| **VRAM Usage** | ❌ | ❌ | ✅ |
| **Version Detection** | ❌ | ❌ | ✅ |
| **Loaded Models** | ❌ | ❌ | ✅ |
| **System Analysis** | ❌ | ❌ | ✅ |
| **Batch Processing** | ❌ | ✅ | ✅ |
| **Progress Tracking** | ✅ | ✅ | ✅ |
| **Error Handling** | Basic | Advanced | Advanced |

**Recommendation**: Use `scan_ollama_hosts_http.py` for most use cases.