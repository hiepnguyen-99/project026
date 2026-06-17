.PHONY: up down migrate revision test logs lint format build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

migrate:
	docker compose exec backend alembic -c src/backend/alembic.ini upgrade head

revision:
	docker compose exec backend alembic -c src/backend/alembic.ini revision --autogenerate -m "$(m)"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
