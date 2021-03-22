#!/usr/bin/env python

from setuptools import setup

setup(name = 'newportxps',
      version = '0.2',
      author = 'Matthew Newville',
      author_email = 'newville@cars.uchicago.edu',
      license = 'BSD',
      description = 'Python interface to Newport XPS controllers',
      packages = ['newportxps'],
      install_requires = ['pysftp']
      )
