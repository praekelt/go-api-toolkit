#!/bin/sh

rm dist/*
python setup.py sdist bdist_wheel
python setup.py register
twine-upload dist/*.tar.gz
