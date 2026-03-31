# Instagram DM Automation — Deployment Guide

## Architecture Overview

```
User Browser → Nginx (SSL/443) → FastAPI (8000) → Azure Cosmos DB
                                                 → Azure Service Bus → Celery Workers
                                                 → Redis Cloud (rate limit, cache)
Meta Webhooks → Nginx → FastAPI /webhooks/instagram → Service Bus → Workers → Instagram API
```

**Services running on your VM:**
- `api` — FastAPI backend (gunicorn + uvicorn)
- `worker` — Celery worker (processes webhooks, sends DMs)
- `beat` — Celery beat (scheduled tasks: token refresh, analytics)
- `nginx` — Reverse proxy with SSL termination

**External services (already configured):**
- Azure Cosmos DB — Database
- Azure Service Bus — Message queue
- Redis Cloud — Rate limiting, caching, deduplication

---

## PHASE 1: GitHub Setup

### Step 1.1 — Create GitHub Repository

```bash
cd ~/Documents/code/personal/secrate/new-automation-backend

# Initialize git repo
git init
git add .
git commit -m "Initial commit: Instagram DM Automation backend"

# Create repo on GitHub (private)
gh repo create new-automation-backend --private --source=. --push
```

Or manually:
1. Go to https://github.com/new
2. Name: `new-automation-backend`, Private
3. Push existing code:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/new-automation-backend.git
   git branch -M main
   git push -u origin main
   ```

### Step 1.2 — Add GitHub Secrets

Go to **GitHub → Your repo → Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Value | Where to get it |
|---|---|---|
| `AZURE_VM_HOST` | Your VM's public IP or DNS | Azure Portal → VM → Overview |
| `AZURE_VM_USER` | `azureuser` (default) or your VM username | Set during VM creation |
| `AZURE_VM_SSH_KEY` | Your private SSH key contents | `cat ~/.ssh/id_rsa` |
| `GHCR_TOKEN` | GitHub Personal Access Token with `read:packages` | GitHub → Settings → Developer settings → PAT |

---

## PHASE 2: Azure VM Setup

### Step 2.1 — Create Azure VM

**Azure Portal → Create a resource → Virtual Machine**

| Setting | Recommended Value |
|---|---|
| Region | Central India (closest to your users) |
| Image | Ubuntu Server 22.04 LTS |
| Size | Standard B2s (2 vCPU, 4 GB RAM) — good for start |
| Authentication | SSH public key |
| Inbound ports | SSH (22), HTTP (80), HTTPS (443) |

**Networking — Add inbound port rules:**
- Port 80 (HTTP) — for Let's Encrypt and redirect
- Port 443 (HTTPS) — for the API
- Port 22 (SSH) — for deployment

### Step 2.2 — DNS Setup

Point your domain to the VM:

1. Get VM public IP from Azure Portal → VM → Overview
2. Go to your DNS provider (where creatrchoice.info is managed)
3. Add an A record:
   ```
   Type: A
   Name: automationapi
   Value: <YOUR_VM_PUBLIC_IP>
   TTL: 300
   ```
4. Verify: `nslookup automationapi.creatrchoice.info` — should return your VM IP

### Step 2.3 — SSH into VM and Install Dependencies

```bash
ssh azureuser@<YOUR_VM_PUBLIC_IP>
```

Run these commands on the VM:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install docker-compose-plugin -y

# Log out and back in for docker group to take effect
exit
```

SSH back in:

```bash
ssh azureuser@<YOUR_VM_PUBLIC_IP>

# Verify Docker works
docker --version
docker compose version
```

### Step 2.4 — Set Up Project Directory on VM

```bash
# Create project directory
mkdir -p ~/dm-automation/nginx/ssl

# Clone your repo (or we'll use GHCR images)
cd ~/dm-automation
```

### Step 2.5 — Copy Configuration Files to VM

**From your local machine** (not the VM):

```bash
cd ~/Documents/code/personal/secrate/new-automation-backend

# Copy .env file (contains secrets — never commit this)
scp .env azureuser@<YOUR_VM_IP>:~/dm-automation/.env

# Copy nginx config
scp nginx/nginx.conf azureuser@<YOUR_VM_IP>:~/dm-automation/nginx/nginx.conf

# Copy production docker-compose
scp docker-compose.prod.yml azureuser@<YOUR_VM_IP>:~/dm-automation/docker-compose.yml
```

### Step 2.6 — Edit docker-compose.yml on VM

SSH into VM and update the image names:

```bash
ssh azureuser@<YOUR_VM_IP>
cd ~/dm-automation

# Replace YOUR_GITHUB_USERNAME with your actual GitHub username
sed -i 's/YOUR_GITHUB_USERNAME/your-actual-username/g' docker-compose.yml
```

---

## PHASE 3: SSL Certificate (Let's Encrypt)

### Step 3.1 — Get SSL Certificate

On the VM:

```bash
# Install certbot
sudo apt install certbot -y

# Get certificate (make sure DNS is pointing to this VM first!)
sudo certbot certonly --standalone -d automationapi.creatrchoice.info

# Certificate files will be at:
#   /etc/letsencrypt/live/automationapi.creatrchoice.info/fullchain.pem
#   /etc/letsencrypt/live/automationapi.creatrchoice.info/privkey.pem
```

### Step 3.2 — Set Up Auto-Renewal

```bash
# Test renewal
sudo certbot renew --dry-run

# Add cron job for auto-renewal (runs twice daily)
sudo crontab -e
# Add this line:
0 0,12 * * * certbot renew --quiet && docker compose -f /home/azureuser/dm-automation/docker-compose.yml restart nginx
```

---

## PHASE 4: Deploy & Start Services

### Step 4.1 — Login to GitHub Container Registry

On the VM:

```bash
# Create a GitHub Personal Access Token at:
# https://github.com/settings/tokens → Generate new token (classic)
# Scopes needed: read:packages

echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

### Step 4.2 — First Deploy (Build Locally)

**Option A: Build directly on VM (simplest for first deploy)**

```bash
cd ~/dm-automation

# Clone the repo
git clone https://github.com/YOUR_USERNAME/new-automation-backend.git repo
cd repo

# Build and start
docker compose -f docker-compose.yml up --build -d

# Check logs
docker compose logs -f
```

**Option B: Use CI/CD (after GitHub Actions is set up)**

Push to `main` branch → GitHub Actions builds images → deploys to VM automatically.

### Step 4.3 — Verify Everything is Running

```bash
# Check all containers are up
docker compose ps

# Expected output:
# dm-automation-api     running (healthy)
# dm-automation-worker  running
# dm-automation-beat    running
# dm-automation-nginx   running

# Test health endpoint
curl http://localhost:8000/health
# {"status": "healthy"}

# Test via HTTPS (from outside)
curl https://automationapi.creatrchoice.info/health
# {"status": "healthy"}

# Check API docs
# Open: https://automationapi.creatrchoice.info/docs
```

### Step 4.4 — Check Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f beat

# Last 100 lines
docker compose logs --tail 100 api
```

---

## PHASE 5: Meta Developer Dashboard Configuration

### Step 5.1 — Configure Webhook

1. Go to https://developers.facebook.com/apps/
2. Select your app (App ID: 1017158637403348)
3. Go to **Webhooks** (left sidebar)
4. Click **Edit Subscription** or **Add Subscription**
5. Set:
   - **Callback URL**: `https://automationapi.creatrchoice.info/webhooks/instagram`
   - **Verify Token**: `instagramautomation`
6. Click **Verify and Save**
7. Subscribe to these fields:
   - `messages` — incoming DMs
   - `messaging_postbacks` — button clicks
   - `messaging_optins` — opt-in events
   - `feed` — comments on posts (if needed)

### Step 5.2 — Configure Instagram Login

1. In your app dashboard, go to **Instagram** → **Settings**
2. Under **Valid OAuth Redirect URIs**, add:
   ```
   https://automationapi.creatrchoice.info/auth/instagram/callback
   ```
3. Under **Deauthorize callback URL** (optional):
   ```
   https://automationapi.creatrchoice.info/auth/instagram/deauthorize
   ```

### Step 5.3 — App Permissions

Make sure these permissions are requested in your app:
- `instagram_basic`
- `instagram_manage_messages`
- `instagram_manage_comments`
- `pages_manage_metadata`
- `pages_messaging`

### Step 5.4 — Test with Instagram Test User

While in Development mode, only test users can trigger webhooks:
1. Go to **App Roles** → **Instagram Testers**
2. Add your Instagram account as a tester
3. Accept the invitation from Instagram app (Settings → Apps and Websites)

---

## PHASE 6: Azure Service Bus Queue Configuration

Your Service Bus namespace is already created. Verify the queue has sessions enabled:

1. Go to **Azure Portal** → **Service Bus** → `creatrchoice`
2. Click on queue `instagram-webhooks`
3. Under **Settings**, verify:
   - **Enable sessions**: ON (required for per-account FIFO ordering)
   - **Max delivery count**: 10
   - **Lock duration**: 30 seconds
   - **Message TTL**: 1 day

If the queue doesn't exist yet:
1. Click **+ Queue**
2. Name: `instagram-webhooks`
3. Enable sessions: **Yes**
4. Click **Create**

---

## PHASE 7: Post-Deploy Verification Checklist

### Test Each Component

```bash
# 1. Health check
curl https://automationapi.creatrchoice.info/health

# 2. Webhook verification (simulates what Meta sends)
curl "https://automationapi.creatrchoice.info/webhooks/instagram?hub.mode=subscribe&hub.verify_token=instagramautomation&hub.challenge=test123"
# Should return: test123

# 3. API docs load
# Open: https://automationapi.creatrchoice.info/docs

# 4. User signup (test auth)
curl -X POST https://automationapi.creatrchoice.info/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"TestPass123!","name":"Test User"}'

# 5. Check Cosmos DB containers were created
# Azure Portal → Cosmos DB → creatrchoice → Data Explorer
# Should see: dm_automation_db with 8 containers

# 6. Check Redis connectivity
docker compose exec api python -c "
from app.db.redis import redis_client
redis_client.ping()
print('Redis OK')
"

# 7. Check worker is consuming from Service Bus
docker compose logs worker | grep "Service Bus"
```

---

## Ongoing Operations

### Update Deployment

```bash
# Push code to main → GitHub Actions auto-deploys
git add .
git commit -m "Update feature X"
git push origin main

# Or manual deploy on VM:
cd ~/dm-automation/repo
git pull
docker compose up --build -d
```

### Restart Services

```bash
cd ~/dm-automation
docker compose restart           # All services
docker compose restart api       # Just API
docker compose restart worker    # Just worker
```

### View Logs

```bash
docker compose logs -f --tail 200 api
docker compose logs -f worker
```

### Scale Workers (High Traffic)

```bash
# Run 3 worker instances
docker compose up -d --scale worker=3
```

### Backup Cosmos DB

Azure Portal → Cosmos DB → Backup & Restore (automatic continuous backups with 30-day retention)

---

## Cost Estimate (Monthly)

| Service | Tier | Estimated Cost |
|---|---|---|
| Azure VM (B2s) | 2 vCPU, 4GB RAM | ~$30/month |
| Azure Cosmos DB | Serverless | ~$5-20/month (usage-based) |
| Azure Service Bus | Basic | ~$5/month |
| Redis Cloud | Free/Essentials | $0-7/month |
| Domain SSL | Let's Encrypt | Free |
| **Total** | | **~$40-62/month** |

---

## Troubleshooting

**Webhook not verifying:**
- Check DNS: `nslookup automationapi.creatrchoice.info`
- Check SSL: `curl -v https://automationapi.creatrchoice.info/health`
- Check nginx logs: `docker compose logs nginx`
- Verify the exact callback URL in Meta dashboard matches

**502 Bad Gateway:**
- API container not healthy: `docker compose ps`
- Check API logs: `docker compose logs api`
- Restart: `docker compose restart api`

**Celery worker not processing:**
- Check Service Bus connection: `docker compose logs worker`
- Verify queue exists in Azure Portal
- Check Redis connection for result backend

**Token refresh failing:**
- Check Celery beat is running: `docker compose ps beat`
- Check beat logs: `docker compose logs beat`
- Verify Instagram tokens in Cosmos DB aren't corrupted
