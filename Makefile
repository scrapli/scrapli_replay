lint:
	python -m isort .
	python -m black .
	python -m pylama .
	python -m pydocstyle .
	python -m mypy --strict scrapli_replay/

darglint:
	find scrapli_cfg -type f \( -iname "*.py"\) | xargs darglint -x

test:
	python -m pytest \
	tests/

cov:
	python -m pytest \
	--cov=scrapli_replay \
	--cov-report html \
	--cov-report term \
	tests/

test_unit:
	python -m pytest \
	tests/unit/

cov_unit:
	python -m pytest \
	--cov=scrapli_replay \
	--cov-report html \
	--cov-report term \
	tests/unit/

deploy_docs:
	mkdocs gh-deploy
