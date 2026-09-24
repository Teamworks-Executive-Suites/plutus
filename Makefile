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

# `lint` is both halves and is what you run locally before a PR.
#
# CI gates on `lint-check` instead — the rules half only. `ruff format --check`
# would fail on 14 files that predate it, and reformatting them is a large
# mechanical diff across code nobody is otherwise touching, which buries real
# history in `git blame` for no behavioural gain. Run `make format` when you
# are already editing a file, and the set shrinks on its own.
.PHONY: lint
lint:
	ruff check app/ tests/
	ruff format app/ tests/ --check

# The half that finds defects rather than preferences: unused imports,
# undefined names, unreachable code. It was passing nowhere until 2026-09-24 —
# CI ran `make test` and nothing else — so three unused imports sat in `main`
# for months.
.PHONY: lint-check
lint-check:
	ruff check app/ tests/

.PHONY: format
format:
	ruff check app/ tests/ --fix
	ruff format app/ tests/