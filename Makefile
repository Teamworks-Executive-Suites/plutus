.PHONY: install
install:
	pip install -r requirements.txt

.PHONY: test
test:
	pytest --cov=app