from setuptools import setup, find_packages

exec(open("greenback/_version.py", encoding="utf-8").read())

LONG_DESC = open("README.rst", encoding="utf-8").read()

setup(
    name="greenback",
    version=__version__,
    description="Reenter an async event loop from synchronous code",
    url="https://github.com/oremanj/greenback",
    long_description=LONG_DESC,
    author="Joshua Oreman",
    author_email="oremanj@gmail.com",
    license="MIT -or- Apache License 2.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "trio",
    ],
    keywords=[
        # COOKIECUTTER-TRIO-TODO: add some keywords
        # "async", "io", "networking", ...
    ],
    python_requires=">=3.6",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Framework :: Trio",
        # COOKIECUTTER-TRIO-TODO: Remove any of these classifiers that don't
        # apply:
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        # COOKIECUTTER-TRIO-TODO: Consider adding trove classifiers for:
        #
        # - Development Status
        # - Intended Audience
        # - Topic
        #
        # For the full list of options, see:
        #   https://pypi.org/classifiers/
    ],
)
