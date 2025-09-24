#!/usr/bin/env python3
"""
Script to parse JSON file and extract hostname/IP and port information
"""

import json
import sys
import socket
import struct

def ip_int_to_str(ip_int):
    """Convert integer IP to string format"""
    return socket.inet_ntoa(struct.pack("!I", ip_int))

def extract_host_port(json_file):
    """Extract host and port information from JSON file"""
    results = []
    
    with open(json_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                
                # Extract host (IP address)
                host = data.get('host')
                
                # If no host field, try to convert ip integer to string
                if not host and 'ip' in data:
                    try:
                        host = ip_int_to_str(data['ip'])
                    except:
                        host = str(data['ip'])
                
                # Extract port (default to 80 for HTTP if not specified)
                port = data.get('port', 80)
                
                # Check if HTTPS is being used
                if 'http' in data and data['http'].get('location', '').startswith('https'):
                    port = data.get('port', 443)
                
                if host:
                    results.append({
                        'host': host,
                        'port': port,
                        'line': line_num
                    })
                    
            except json.JSONDecodeError as e:
                print(f"Error parsing line {line_num}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Error processing line {line_num}: {e}", file=sys.stderr)
    
    return results

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 extract_hosts.py <json_file>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    
    try:
        results = extract_host_port(json_file)
        
        print("Host:Port pairs found:")
        print("-" * 30)
        
        for result in results:
            print(f"{result['host']}:{result['port']}")
            
        print(f"\nTotal hosts found: {len(results)}")
        
        # Also save to file
        with open('hosts_and_ports.txt', 'w') as f:
            for result in results:
                f.write(f"{result['host']}:{result['port']}\n")
        
        print("Results saved to hosts_and_ports.txt")
        
    except FileNotFoundError:
        print(f"Error: File '{json_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()