"""Guided, resumable NomoSmart Kubernetes installer."""

from .config import InstallConfig, load_config

__version__ = "0.2.0"

__all__ = ["InstallConfig", "load_config"]
