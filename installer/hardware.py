"""Hardware detection for the Installer System.

Detects CPU, RAM, GPU, and Storage so the installer can recommend
the right AI model and warn about insufficient hardware.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from enum import Enum

import psutil

from core.logger import get_logger

logger = get_logger("installer.hardware")

if sys.platform == "win32":
    import win32com.client


class GPUBrand(str, Enum):
    NVIDIA = "NVIDIA"
    AMD = "AMD"
    INTEL = "Intel"
    UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    gpu_brand: GPUBrand
    gpu_name: str
    gpu_vram_gb: float | None
    storage_total_gb: float
    storage_free_gb: float
    cuda_available: bool


@dataclass(frozen=True, slots=True)
class ModelRecommendation:
    model_size_b: int
    label: str
    reason: str


_MIN_RAM_GB = {
    "3b": 4,
    "7b": 8,
    "14b": 16,
    "32b": 32,
    "70b": 64,
}


def _detect_cpu() -> tuple[str, int, int]:
    name = platform.processor() or "Unknown CPU"
    cores = psutil.cpu_count(logical=False) or 1
    threads = psutil.cpu_count(logical=True) or 1
    return name, cores, threads


def _detect_ram() -> tuple[float, float]:
    mem = psutil.virtual_memory()
    return mem.total / (1024**3), mem.available / (1024**3)


def _detect_gpu() -> tuple[GPUBrand, str, float | None, bool]:
    if sys.platform != "win32":
        return GPUBrand.UNKNOWN, "", None, False
    try:
        wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        svc = wmi.ConnectServer(".", "root\\cimv2")
        gpu_query = svc.ExecQuery("SELECT * FROM Win32_VideoController")
        for gpu in gpu_query:
            name = gpu.Name or ""
            vram_mb = gpu.AdapterRAM
            vram_gb = (vram_mb / (1024**2)) if vram_mb else None
            brand = GPUBrand.NVIDIA if "nvidia" in name.lower() else (
                GPUBrand.AMD if "amd" in name.lower() or "radeon" in name.lower() else (
                    GPUBrand.INTEL if "intel" in name.lower() else GPUBrand.UNKNOWN
                )
            )
            cuda = brand == GPUBrand.NVIDIA
            return brand, name, vram_gb, cuda
    except Exception:
        logger.exception("GPU detection failed")
    return GPUBrand.UNKNOWN, "", None, False


def _detect_storage() -> tuple[float, float]:
    usage = psutil.disk_usage("/")
    return usage.total / (1024**3), usage.free / (1024**3)


def detect_hardware() -> HardwareProfile:
    """Run all hardware probes and return a unified profile."""
    cpu_name, cpu_cores, cpu_threads = _detect_cpu()
    ram_total, ram_avail = _detect_ram()
    gpu_brand, gpu_name, gpu_vram, cuda = _detect_gpu()
    storage_total, storage_free = _detect_storage()
    return HardwareProfile(
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        cpu_threads=cpu_threads,
        ram_total_gb=round(ram_total, 1),
        ram_available_gb=round(ram_avail, 1),
        gpu_brand=gpu_brand,
        gpu_name=gpu_name,
        gpu_vram_gb=round(gpu_vram, 1) if gpu_vram is not None else None,
        storage_total_gb=round(storage_total, 1),
        storage_free_gb=round(storage_free, 1),
        cuda_available=cuda,
    )


def recommend_model(profile: HardwareProfile | None = None) -> ModelRecommendation:
    """Recommend a model size based on detected hardware.

    Uses RAM as the primary signal (models must fit in memory for
    CPU inference; GPU VRAM is a secondary signal for CUDA acceleration).
    """
    if profile is None:
        profile = detect_hardware()

    ram_gb = profile.ram_total_gb
    vram_gb = profile.gpu_vram_gb

    # GPU with VRAM >= 12 GB can handle 14B comfortably
    if vram_gb is not None and vram_gb >= 12:
        return ModelRecommendation(
            model_size_b=14_000_000_000,
            label="14B (CUDA)",
            reason=f"GPU has {vram_gb:.0f} GB VRAM — 14B model fits with CUDA acceleration",
        )
    # GPU with VRAM 6-12 GB: 7B with CUDA
    if vram_gb is not None and vram_gb >= 6:
        return ModelRecommendation(
            model_size_b=7_000_000_000,
            label="7B (CUDA)",
            reason=f"GPU has {vram_gb:.0f} GB VRAM — 7B model fits with CUDA acceleration",
        )
    # RAM-based recommendations
    for label, size_b in [("70b", 70_000_000_000), ("32b", 32_000_000_000),
                           ("14b", 14_000_000_000), ("7b", 7_000_000_000),
                           ("3b", 3_000_000_000)]:
        min_ram = _MIN_RAM_GB[label]
        if ram_gb >= min_ram:
            return ModelRecommendation(
                model_size_b=size_b,
                label=label,
                reason=f"{ram_gb:.0f} GB RAM meets the {min_ram} GB minimum for {label}",
            )
    # Fallback: 3B is the smallest
    return ModelRecommendation(
        model_size_b=3_000_000_000,
        label="3b",
        reason=f"{ram_gb:.0f} GB RAM is below all thresholds; 3B is the minimum viable model",
    )
