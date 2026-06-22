#!/usr/bin/env python3
"""Kvitto-appen – startpunkt"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.app import KvittoApp

if __name__ == "__main__":
    app = KvittoApp()
    app.run()
