#!/usr/bin/env python3
"""
Generate and seed sample data for testing
"""

import json
import random
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from app.db import init_db, engine, Host, Model, HostModel, Scan
from datetime import datetime, timedelta


def generate_sample_data():
    """Generate sample JSON data file"""
    hosts = []
    
    for i in range(100):
        host = {
            "ip": f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
            "port": random.choice([11434, 11435, 8080]),
            "country": random.choice(["US", "UK", "DE", "FR", "JP", "CN"]),
            "city": random.choice(["New York", "London", "Berlin", "Paris", "Tokyo", "Beijing"])
        }
        hosts.append(host)
    
    # Save to file
    sample_file = Path("data/sample.json")
    sample_file.parent.mkdir(exist_ok=True)
    
    with open(sample_file, "w") as f:
        for host in hosts:
            f.write(json.dumps(host) + "\n")
    
    print(f"Generated {len(hosts)} sample hosts in {sample_file}")
    return sample_file


def seed_database():
    """Seed database with sample data"""
    from app.db import engine as db_engine
    
    # Initialize database
    init_db()
    
    # Use the initialized engine
    with Session(db_engine) as session:
        # Add sample models
        models = [
            Model(name="llama2:7b", family="llama", parameters="7B"),
            Model(name="llama2:13b", family="llama", parameters="13B"),
            Model(name="mistral:7b", family="mistral", parameters="7B"),
            Model(name="mixtral:8x7b", family="mixtral", parameters="56B"),
            Model(name="codellama:7b", family="codellama", parameters="7B"),
            Model(name="phi:2.7b", family="phi", parameters="2.7B"),
        ]
        
        for model in models:
            existing = session.exec(
                select(Model).where(Model.name == model.name)
            ).first()
            if not existing:
                session.add(model)
        
        session.commit()
        
        # Add sample hosts
        for i in range(20):
            host = Host(
                ip=f"192.168.{random.randint(1, 10)}.{random.randint(1, 254)}",
                port=11434,
                status=random.choice(["online", "offline", "error"]),
                last_seen=datetime.utcnow() - timedelta(minutes=random.randint(0, 1440)),
                latency_ms=random.uniform(10, 200) if random.random() > 0.3 else None,
                api_version="0.1.23" if random.random() > 0.5 else None,
                gpu_vram_mb=random.choice([0, 8192, 16384, 24576]) if random.random() > 0.3 else None,
                geo_country=random.choice(["US", "UK", "DE", "FR"]),
                geo_city=random.choice(["San Francisco", "London", "Berlin", "Paris"])
            )
            
            session.add(host)
            session.flush()
            
            # Add random models to host
            num_models = random.randint(1, 3)
            selected_models = random.sample(models, num_models)
            
            for model in selected_models:
                host_model = HostModel(
                    host_id=host.id,
                    model_id=model.id,
                    loaded=random.random() > 0.7,
                    vram_usage_mb=random.randint(2000, 8000) if host.gpu_vram_mb else None
                )
                session.add(host_model)
        
        # Add sample scan
        scan = Scan(
            source_file="data/sample.json",
            status="completed",
            started_at=datetime.utcnow() - timedelta(hours=1),
            completed_at=datetime.utcnow(),
            mapping_json=json.dumps({"ip": "ip", "port": "port"}),
            stats_json=json.dumps({"success": 95, "failed": 5}),
            total_rows=100,
            processed_rows=100
        )
        session.add(scan)
        
        session.commit()
        
        print(f"Seeded database with {len(models)} models and 20 hosts")


if __name__ == "__main__":
    print("Seeding sample data...")
    
    # Generate sample file
    sample_file = generate_sample_data()
    
    # Seed database
    seed_database()
    
    print("\nSample data seeded successfully!")
    print("You can now:")
    print(f"  1. Run 'make ingest file={sample_file}' to test ingestion")
    print("  2. Visit http://localhost:5173 to explore the data")
    print("  3. Run 'make probe filter=--all' to probe all hosts")