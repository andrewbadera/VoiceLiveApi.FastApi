#!/usr/bin/env python3
"""
Startup script for Voice Live API FastAPI server
"""
import sys
import os

# Check if .env file exists
if not os.path.exists('.env'):
    print("⚠️  Warning: .env file not found!")
    print("Please copy .env.example to .env and configure your Azure credentials.")
    print("\nExample:")
    print("  cp .env.example .env")
    print("  # Then edit .env with your credentials")
    print()
    response = input("Continue anyway? (y/n): ")
    if response.lower() != 'y':
        sys.exit(1)

# Import and run main
from main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8080,
        log_level="debug",
        access_log=True
    )
