#!/usr/bin/env python3
"""Simple data seeder for testing"""

from sqlmodel import Session, create_engine, SQLModel
from app.db import Host, Model, HostModel, Scan
from datetime import datetime, timedelta
import random
import json

# Create engine
DATABASE_URL = "sqlite:////app/data/ollama.db"
engine = create_engine(DATABASE_URL, echo=False)
SQLModel.metadata.create_all(engine)

with Session(engine) as session:
    # Add sample models
    models = []
    model_names = [
        ("llama2:7b", "llama", "7B"),
        ("llama2:13b", "llama", "13B"),
        ("mistral:7b", "mistral", "7B"),
        ("codellama:7b", "codellama", "7B"),
    ]
    
    for name, family, params in model_names:
        model = Model(name=name, family=family, parameters=params)
        session.add(model)
        models.append(model)
    
    session.commit()
    
    # Add sample hosts
    for i in range(10):
        host = Host(
            ip=f"192.168.1.{i+1}",
            port=11434,
            status=random.choice(["online", "offline"]),
            last_seen=datetime.utcnow() - timedelta(minutes=random.randint(0, 60)),
            latency_ms=random.uniform(10, 100),
            api_version="0.1.23",
            gpu_vram_mb=random.choice([0, 8192, 16384]) if random.random() > 0.5 else None,
            geo_country="US",
            geo_city="San Francisco"
        )
        session.add(host)
        session.flush()
        
        # Add random models to host
        num_models = random.randint(1, 2)
        for model in random.sample(models, num_models):
            host_model = HostModel(
                host_id=host.id,
                model_id=model.id,
                loaded=random.random() > 0.5
            )
            session.add(host_model)
    
    session.commit()
    print("Database seeded with sample data!")