.PHONY: install run lint format typecheck test js-check check docker

install:
	pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload

lint:
	ruff check .

format:
	ruff format --check .

typecheck:
	mypy --strict app

js-check:
	node --check static/app.js

test:
	python -m pytest

check: lint format typecheck js-check test

docker:
	docker build -t urban-air-quality-assistant .
	docker run --rm -p 8000:8000 --env-file .env urban-air-quality-assistant
