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
    install_requires=["greenlet", "sniffio", "outcome",],
    keywords=["async", "io", "trio", "asyncio",],
    python_requires=">=3.6",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Framework :: Trio",
        "Framework :: AsyncIO",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Development Status :: 4 - Beta",
    ],
)
