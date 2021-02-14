lint:
	python -m isort .
	python -m black .
	python -m pylama .
	python -m pydocstyle .
	python -m mypy --strict scrapli_replay/

cov:
	python -m pytest \
	--cov=scrapli_replay \
	--cov-report html \
	--cov-report term \
	tests/

deploy_docs:
	mkdocs gh-deploy
