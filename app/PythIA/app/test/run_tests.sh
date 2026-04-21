#!/bin/sh
set -eu

coverage erase
coverage run --source=app -m unittest discover -s tests/unit -t .
coverage run --append --source=app -m unittest discover -s tests/integration -t .
coverage xml -o coverage.xml
coverage report -m
coverage html -d coverage
