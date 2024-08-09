lint:
	python -m isort .
	python -m black .
	python -m pylint scrapli_replay/
	python -m pydocstyle .
	python -m mypy --strict scrapli_replay/

darglint:
	find scrapli_replay -type f \( -iname "*.py"\ ) | xargs darglint -x

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

test_docs:
	mkdocs build --clean --strict
	htmltest -c docs/htmltest.yml -s
	rm -rf tmp

deploy_docs:
	mkdocs gh-deploy
