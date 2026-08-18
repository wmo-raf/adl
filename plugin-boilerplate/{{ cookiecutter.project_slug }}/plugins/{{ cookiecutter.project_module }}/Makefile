lint:
	flake8 src

lint-python: lint

format:
	black . --extend-exclude='/generated/' || exit;
