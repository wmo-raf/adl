lint:
	flake8 src tests && \
	black . --extend-exclude='/generated/' --check && \
	bandit -r src/ \
	|| exit;

lint-python: lint

format:
	black . --extend-exclude='/generated/' || exit;
