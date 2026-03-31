# Instagram DM Automation Backend

FastAPI backend for automating Instagram DMs triggered by comments, story reactions, and incoming messages.

## Tech Stack

- **Framework:** FastAPI (Python 3.11)
- **Database:** Azure Cosmos DB
- **Task Queue:** Celery + Redis
- **Encryption:** Azure Key Vault (production) / AES-256-GCM (dev fallback)
- **Message Queue:** Azure Service Bus (optional, falls back to Redis)
- **Reverse Proxy:** Nginx
- **Containerization:** Docker + Docker Compose

## Project Structure

```
├── app/
│   ├── api/            # Route handlers
│   │   ├── auth.py           # Authentication & Instagram OAuth
│   │   ├── webhooks.py       # Instagram webhook endpoints
│   │   ├── accounts.py       # Instagram account management
│   │   ├── automations.py    # Automation CRUD
│   │   ├── contacts.py       # Contact management
│   │   └── analytics.py      # Analytics & reporting
│   ├── core/           # App config & settings
│   ├── db/             # Cosmos DB client & containers
│   ├── models/         # Data models
│   ├── schemas/        # Pydantic schemas
│   ├── services/       # Business logic
│   ├── tasks/          # Celery task definitions
│   └── workers/        # Background workers
├── main.py             # FastAPI app entrypoint
├── docker-compose.yml  # Multi-service orchestration
├── Dockerfile          # API server image
├── Dockerfile.worker   # Celery worker image
└── requirements.txt    # Python dependencies
```

## Getting Started

### Prerequisites

- Python 3.11+
- Redis
- Azure Cosmos DB account
- Meta Developer App (for Instagram API)

### Local Development

1. **Clone and set up environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run the API server:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```

4. **Run the Celery worker** (separate terminal):
   ```bash
   celery -A app.tasks.celery_app worker --loglevel=info
   ```

5. **Run the Celery beat scheduler** (separate terminal):
   ```bash
   celery -A app.tasks.celery_app beat --loglevel=info
   ```

### Docker

```bash
docker compose up --build
```

This starts all services:

| Service  | Description             | Port |
|----------|-------------------------|------|
| `api`    | FastAPI server          | 8000 |
| `worker` | Celery worker           | —    |
| `beat`   | Celery beat scheduler   | —    |
| `nginx`  | Reverse proxy           | 80, 443 |

## API Documentation

Once running, interactive docs are available at:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Key Endpoints

| Method | Endpoint                        | Description                     |
|--------|----------------------------------|---------------------------------|
| POST   | `/auth/instagram/callback`       | Instagram OAuth callback        |
| GET    | `/webhooks/instagram`            | Webhook verification (Meta)     |
| POST   | `/webhooks/instagram`            | Receive Instagram events        |
| GET    | `/api/v1/accounts`               | List connected IG accounts      |
| CRUD   | `/api/v1/automations`            | Manage DM automations           |
| GET    | `/api/v1/contacts`               | View contacts/conversations     |
| GET    | `/api/v1/analytics`              | View analytics & reports        |

## Environment Variables

See [`.env.example`](.env.example) for the full list of required and optional configuration.
