#!/bin/sh
set -eu

coverage erase
coverage run --source=app/main -m unittest discover -s app/test/unit -t .
coverage run --append --source=app/main -m unittest discover -s app/test/integration -t .
coverage xml -o coverage.xml
coverage report -m
coverage html -d coverage
