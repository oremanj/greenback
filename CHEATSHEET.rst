Finishing setting up your project
=================================

Thanks for using cookiecutter-trio! This is your project now; you can
customize it however you like. Here's some reminders of things you
might want to do to get started:

* Enable `Read the Docs <https://readthedocs.org>`__. (Note: this
  project contains a ``.readthedocs.yml`` file that should be enough
  to get things working.)

* Set up continuous integration: Currently, this project is set up to
  test on Linux, MacOS, and Windows using Azure Pipelines, and to test
  some additional Python versions on Linux (PyPy and nightly) using
  Travis.

  If that's what you want, then go to Travis and Azure Pipelines and enable
  testing for your repo.

  If that's not what you want, then you can trim the list by modifying
  (or deleting) ``.travis.yml``, ``azure-pipelines.yml``, ``ci.sh``.

* Enable `Codecov <https://codecov.io>`__ for your repo.

* If you want to use static typing (mypy) in your project:

  * Update ``install_requires`` in ``setup.py`` to include ``"trio-typing"``
    (assuming you use it).

  * Uncomment the dependency on ``mypy`` in ``test-requirements.txt``.

  * Uncomment the mypy invocation in ``check.sh``.

  * Create an empty ``greenback/py.typed`` file,
    and add ``"include greenback/py.typed"`` to
    ``MANIFEST.in``.

* File bugs or pull requests on `cookiecutter-trio
  <https://github.com/python-trio/cookiecutter-trio>`__ reporting any
  problems or awkwardness you ran into (no matter how small!)

* Delete this checklist once it's no longer useful


Tips
====

To run tests
------------

* Install requirements: ``pip install -r test-requirements.txt``
  (possibly in a virtualenv)

* Actually run the tests: ``pytest greenback``


To run black
------------

* Show what changes black wants to make: ``black --diff setup.py
  greenback``

* Apply all changes directly to the source tree: ``black setup.py
  greenback``


To make a release
-----------------

* Update the version in ``greenback/_version.py``

* Run ``towncrier`` to collect your release notes.

* Review your release notes.

* Check everything in.

* Double-check it all works, docs build, etc.

* Build your sdist and wheel: ``python setup.py sdist bdist_wheel``

* Upload to PyPI: ``twine upload dist/*``

* Use ``git tag`` to tag your version.

* Don't forget to ``git push --tags``.
