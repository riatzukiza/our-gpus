import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.db import Host, Probe

logger = logging.getLogger(__name__)


class ProbeService:
    def __init__(self):
        self.timeout = settings.probe_timeout_secs
        self.retries = settings.probe_retries
        self.concurrency = settings.probe_concurrency

    async def probe_host(self, host: Host) -> Probe:
        """Probe a single Ollama host"""
        start_time = datetime.utcnow()
        base_url = f"http://{host.ip}:{host.port}"

        for attempt in range(self.retries):
            try:
                async with httpx.AsyncClient(
                    verify=False, timeout=httpx.Timeout(self.timeout, connect=self.timeout)
                ) as client:
                    # Collect all API data
                    tags_resp = await client.get(f"{base_url}/api/tags")
                    ps_resp = await client.get(f"{base_url}/api/ps")
                    version_resp = await client.get(f"{base_url}/api/version")

                    if tags_resp.status_code == 200:
                        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                        # Parse responses
                        tags_data = tags_resp.json()
                        ps_data = ps_resp.json() if ps_resp.status_code == 200 else {}
                        version_data = (
                            version_resp.json() if version_resp.status_code == 200 else {}
                        )

                        # Update host info
                        host.status = "online"
                        host.last_seen = datetime.utcnow()
                        host.latency_ms = duration_ms
                        host.api_version = version_data.get("version", "unknown")

                        # Process GPU info from ps endpoint and model details
                        gpu_detected = False
                        total_vram = 0

                        # Check running models for GPU usage
                        if "models" in ps_data:
                            for model in ps_data.get("models", []):
                                vram = model.get("size_vram", 0)
                                if isinstance(vram, (int, float)) and vram > 0:
                                    total_vram += int(vram)
                                    gpu_detected = True

                        # Infer GPU availability from model sizes
                        # Large models (>10GB) typically require GPU
                        if not gpu_detected and "models" in tags_data:
                            for model in tags_data.get("models", []):
                                model_size = model.get("size", 0)
                                # Models > 10GB usually indicate GPU availability
                                if model_size > 10 * 1024 * 1024 * 1024:  # 10GB
                                    gpu_detected = True
                                    break

                                # Also check parameter size
                                details = model.get("details", {})
                                param_size = details.get("parameter_size", "")
                                if param_size:
                                    # Extract number from strings like "70B", "13B", etc
                                    import re

                                    match = re.search(r"(\d+(?:\.\d+)?)[Bb]", param_size)
                                    if match:
                                        size_b = float(match.group(1))
                                        # Models with 13B+ parameters typically need GPU
                                        if size_b >= 13:
                                            gpu_detected = True
                                            break

                        if gpu_detected or total_vram > 0:
                            host.gpu = "available"
                            if total_vram > 0:
                                host.gpu_vram_mb = total_vram // (1024 * 1024)
                            else:
                                # GPU likely available but VRAM unknown
                                host.gpu_vram_mb = None
                        else:
                            host.gpu = None
                            host.gpu_vram_mb = None

                        # Create probe record with limited model data to avoid truncation
                        # Only store first 10 models to keep payload size reasonable
                        limited_tags_data = tags_data.copy()
                        if "models" in limited_tags_data and len(limited_tags_data["models"]) > 10:
                            limited_tags_data["models"] = limited_tags_data["models"][:10]
                            limited_tags_data["total_models"] = len(tags_data.get("models", []))

                        probe = Probe(
                            host_id=host.id,
                            status="success",
                            duration_ms=duration_ms,
                            raw_payload=json.dumps(
                                {"tags": limited_tags_data, "ps": ps_data, "version": version_data}
                            ),
                            error=None,
                        )

                        return probe

                    elif 400 <= tags_resp.status_code < 500:
                        # Non-Ollama HTTP service
                        host.status = "non_ollama"
                        return Probe(
                            host_id=host.id,
                            status="non_ollama",
                            duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                            raw_payload="",
                            error=f"HTTP {tags_resp.status_code}",
                        )

            except httpx.TimeoutException:
                if attempt == self.retries - 1:
                    host.status = "timeout"
                    return Probe(
                        host_id=host.id,
                        status="timeout",
                        duration_ms=self.timeout * 1000,
                        raw_payload="",
                        error="Connection timeout",
                    )
                await asyncio.sleep(1 * (2**attempt))

            except Exception as e:
                if attempt == self.retries - 1:
                    host.status = "error"
                    return Probe(
                        host_id=host.id,
                        status="error",
                        duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                        raw_payload="",
                        error=str(e)[:500],
                    )
                await asyncio.sleep(0.5 * (2**attempt))

        # If all retries failed without returning
        host.status = "error"
        return Probe(
            host_id=host.id,
            status="error",
            duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
            raw_payload="",
            error="All retries exhausted",
        )

    def extract_models(self, tags_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract model information from tags response"""
        models = []
        if "models" in tags_data and isinstance(tags_data["models"], list):
            for model in tags_data["models"]:
                if isinstance(model, dict) and "name" in model:
                    # Parse model name to extract family
                    name = model["name"]
                    family = self._extract_family(name)

                    models.append(
                        {
                            "name": name,
                            "family": family,
                            "size": model.get("size"),
                            "parameters": self._extract_parameters(model),
                            "digest": model.get("digest"),
                        }
                    )
        return models

    def _extract_family(self, model_name: str) -> str:
        """Extract model family from name"""
        families = [
            "codellama",  # Check more specific names first
            "deepseek",
            "mixtral",
            "mistral",
            "vicuna",
            "llama",
            "gemma",
            "qwen",
            "phi",
        ]
        name_lower = model_name.lower()
        for family in families:
            if family in name_lower:
                return family
        return "other"

    def _extract_parameters(self, model_data: dict[str, Any]) -> str | None:
        """Extract parameter size from model data"""
        if "details" in model_data and isinstance(model_data["details"], dict):
            return model_data["details"].get("parameter_size")

        # Try to extract from name
        name = model_data.get("name", "")
        match = re.search(r"(\d+(?:\.\d+)?)[bB]", name)
        if match:
            return match.group(0)

        return None

    async def run_prompt(
        self, host_ip: str, host_port: int, model: str, prompt: str, stream: bool = False
    ) -> dict[str, Any]:
        """Run a prompt against an Ollama instance"""
        base_url = f"http://{host_ip}:{host_port}"

        try:
            async with httpx.AsyncClient(
                verify=False, timeout=httpx.Timeout(30.0, connect=10.0)
            ) as client:
                # Prepare the request payload
                payload = {"model": model, "prompt": prompt, "stream": stream}

                # Make the generation request
                response = await client.post(f"{base_url}/api/generate", json=payload, timeout=30.0)

                if response.status_code == 200:
                    if stream:
                        # For streaming, we'll handle it differently in the future
                        # For now, just return the non-streaming response
                        return response.json()
                    else:
                        result = response.json()
                        return {
                            "success": True,
                            "response": result.get("response", ""),
                            "model": model,
                            "done": result.get("done", True),
                            "context": result.get("context", []),
                            "total_duration": result.get("total_duration", 0),
                            "load_duration": result.get("load_duration", 0),
                            "prompt_eval_duration": result.get("prompt_eval_duration", 0),
                            "eval_duration": result.get("eval_duration", 0),
                            "eval_count": result.get("eval_count", 0),
                        }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                    }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timeout - the model may be loading or the prompt is too complex",
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": f"Could not connect to host at {host_ip}:{host_port}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def stream_prompt(
        self, host_ip: str, host_port: int, model: str, prompt: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a prompt response from an Ollama instance"""
        base_url = f"http://{host_ip}:{host_port}"

        try:
            async with httpx.AsyncClient(
                verify=False, timeout=httpx.Timeout(60.0, connect=10.0)
            ) as client:
                payload = {"model": model, "prompt": prompt, "stream": True}

                async with client.stream(
                    "POST", f"{base_url}/api/generate", json=payload, timeout=60.0
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                    yield {
                                        "type": "token",
                                        "content": data.get("response", ""),
                                        "done": data.get("done", False),
                                        "model": data.get("model"),
                                        "total_duration": data.get("total_duration"),
                                        "load_duration": data.get("load_duration"),
                                        "prompt_eval_duration": data.get("prompt_eval_duration"),
                                        "eval_duration": data.get("eval_duration"),
                                        "eval_count": data.get("eval_count"),
                                    }
                                    if data.get("done", False):
                                        break
                                except json.JSONDecodeError as e:
                                    yield {
                                        "type": "error",
                                        "content": f"JSON decode error: {str(e)}",
                                    }
                                    continue
                    else:
                        error_text = await response.aread()
                        yield {
                            "type": "error",
                            "content": f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='ignore')}",
                        }

        except httpx.TimeoutException:
            yield {
                "type": "error",
                "content": "Request timeout - the model may be loading or the prompt is too complex",
            }
        except httpx.ConnectError:
            yield {
                "type": "error",
                "content": f"Could not connect to host at {host_ip}:{host_port}",
            }
        except Exception as e:
            yield {"type": "error", "content": f"Unexpected error: {str(e)}"}
