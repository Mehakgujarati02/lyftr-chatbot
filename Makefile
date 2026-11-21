.PHONY: up down logs build restart test clean dev-backend dev-frontend

up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - add your real LLM_API_KEYS")
	docker compose up -d --build
	@echo "Backend:  http://localhost:8000/health"
	@echo "Frontend: http://localhost:3000"

down:
	docker compose down

build:
	docker compose build

restart:
	docker compose restart

logs:
	docker compose logs -f

test:
	cd backend && python -m pytest -q

# Removes containers AND the SQLite volume (deletes chat history)
clean:
	docker compose down -v

dev-backend:
	cd backend && DATABASE_URL=sqlite:///./app.db uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm install && npm run dev
