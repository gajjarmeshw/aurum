---
name: Production_Deployment
description: Manages the EC2 server orchestration, systemd services, and Nginx proxy configuration.
---

# Production Deployment Skill

This skill governs the infrastructure setup and maintenance for AURUM Pro on AWS EC2 (Ubuntu).

## Infrastructure Specifics

### 1. Systemd: `deploy/aurum.service`
- **User**: `ubuntu`.
- **Path**: `/home/ubuntu/aurum`.
- **Environment**: `PYTHONUNBUFFERED=1`.
- **Restart**: `always` with 5s delay.

### 2. Nginx: `deploy/nginx.conf`
- **Port**: Listens on 80, proxies to `127.0.0.1:5000`.
- **SSE Support**: Requires `proxy_set_header Connection "";` and `proxy_http_version 1.1;` to prevent stream dropping.
- **Config Path**: `/etc/nginx/sites-available/aurum`.

### 3. Server: `main.py`
- **Process 1**: `DataPipeline` (Daemon=True).
- **Process 2**: `WebServer` (Daemon=True).
- **Shutdown**: Handles `SIGINT` and `SIGTERM` to terminate both processes cleanly.

## Deployment Steps

### 1. Install Systemd Service
```bash
sudo cp deploy/aurum.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aurum
sudo systemctl start aurum
```

### 2. Configure Nginx
```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/aurum
sudo ln -s /etc/nginx/sites-available/aurum /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Monitoring
- **Logs**: `sudo journalctl -u aurum -f`
- **Process Status**: `ps -ef | grep main.py`
- **Output File**: `tail -f output.log`

## Common Fixes
- **Port Conflict**: Use `pkill -9 -f "python main.py"` if the service fails to start due to a lingering `nohup` process.
- **Venv Issues**: Ensure `aurum.service` points to the correct `/home/ubuntu/aurum/venv/bin/python` path.
