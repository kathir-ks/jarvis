# Jarvis Agent Platform - MVP

Personal AI agent platform built with FastAPI, MongoDB, Redis, and Celery.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)

### Run with Docker Compose

```bash
# Copy environment template
cd docker
cp .env.example .env

# Start all services
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start dependencies (MongoDB, Redis, Qdrant)
cd docker
docker-compose up -d mongodb redis qdrant

# Run API server
cd ..
uvicorn jarvis.app.main:app --reload

# Run Celery worker (separate terminal)
celery -A jarvis.app.tasks.celery_app worker --loglevel=info
```

## Project Structure

```
jarvis/
  app/
    api/routes/        # FastAPI routers
    core/              # Settings, logging, app factory
    models/            # Pydantic DTOs
    services/          # Business logic facades
    runtime/           # Agent event loop & DAG executor
    tasks/             # Celery task definitions
    messaging/         # Redis Pub/Sub messaging
    llm/               # LLM gateway & tool registry
    integrations/      # Adapters & browser automation
    db/                # DB clients (Motor, Redis, Qdrant)
    utils/             # Helpers
  docker/              # Docker Compose & Dockerfile
```

## API Endpoints

- `GET /health` - Health check
- `POST /agents` - Create agent
- `GET /agents/{agent_id}` - Get agent state
- `POST /agents/{agent_id}/tasks` - Submit task
- `GET /tasks/{task_id}` - Get task status
- `POST /messages` - Send message between agents

## Documentation

- [HLD.txt](HLD.txt) - High-Level Design
- [LLD.md](LLD.md) - Low-Level Design
- [Requirement.txt](Requirement.txt) - Requirements

## Environment Variables

See `docker/.env.example` for configuration options.

## Development Status

**MVP Phase** - Core scaffolding complete. Next steps:
- Wire services to MongoDB repositories
- Implement agent runtime loop with Redis Pub/Sub
- Add LLM provider integrations
- Build sample adapters (e-commerce, search)

## License

Proprietary
