.PHONY: install
install:
	pip install -r requirements.txt
	pip install -r ./tests/test_requirements.txt

.PHONY: uninstall
uninstall:
	pip uninstall -y -r <(pip freeze)

.PHONY: test
test:
	pytest --cov=app

.PHONY: start
start:
	uvicorn app.main:app --reload

.PHONY: lint
lint:
	ruff check app/ tests/
	ruff format app/ tests/ --check

.PHONY: format
format:
	ruff check app/ tests/ --fix
	ruff format app/ tests/