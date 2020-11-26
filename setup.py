#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name='kws_streaming',
    version='0.0.1',
    description='Google Research\'s KWS streaming code',
    author='Google Research',
    url='https://github.com/google-research/google-research/tree/master/kws_streaming',
    packages=find_packages(),
    install_requires=[
        'absl-py>=0.7.0',
        'numpy>=1.13.3',
        'tensorflow>=2.3.0', # was validated on tf_nightly-2.3.0.dev20200515-cp36-cp36m-manylinux2010_x86_64.whl
    ],
)
