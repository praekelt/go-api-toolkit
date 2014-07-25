#!/bin/sh -e

rm dist/* || true
python setup.py sdist
python setup.py register
twine-upload dist/*
