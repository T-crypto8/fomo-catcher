#!/usr/bin/env python3
"""
FOMO Catcher — Live Dashboard Server
Serves dashboard.html + trade_log.json on localhost.
Auto-refreshes with real paper trading data.
"""

import http.server
import socketserver
import json
import os
import threading
import subprocess
import sys
import time

PORT = 8888
DIR = os.path.dirname(os.path.abspath(__file__))

class FOMOHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        if self.path == '/api/trades':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                with open(os.path.join(DIR, 'trade_log.json'), 'r') as f:
                    data = f.read()
            except:
                data = '[]'
            self.wfile.write(data.encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # Suppress logs

def run_agent():
    """Run paper trading agent in background."""
    print("[Server] Starting paper trading agent...")
    subprocess.Popen(
        [sys.executable, os.path.join(DIR, 'agent.py'), '--paper', '--interval', '30'],
        cwd=DIR
    )

if __name__ == '__main__':
    # Start agent in background
    run_agent()
    time.sleep(2)

    # Start web server
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), FOMOHandler) as httpd:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║   FOMO Catcher — Live Dashboard Server                  ║
    ║                                                         ║
    ║   Dashboard:  http://localhost:{PORT}/dashboard.html       ║
    ║   Trade API:  http://localhost:{PORT}/api/trades            ║
    ║   Agent:      Paper trading (real prices, 30s interval)  ║
    ║                                                         ║
    ║   Press Ctrl+C to stop                                  ║
    ╚══════════════════════════════════════════════════════════╝
        """)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[Server] Shutting down...")
