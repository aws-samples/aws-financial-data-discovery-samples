.PHONY: setup build deploy format clean

setup:
	python3 -m venv .venv
	.venv/bin/python3 -m pip install -U pip
	.venv/bin/python3 -m pip install -r requirements-dev.txt
	.venv/bin/python3 -m pip install -r dependencies/requirements.txt

build:
	sam build

deploy:
	sam deploy

clean:
	rm -rf .venv .aws-sam

format:
	.venv/bin/black .
