#!/usr/bin/env python3
"""Compatibility entry point for the installed root-owned depth service."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'src/jarvis/vision/depth_service.py'), run_name='__main__')
