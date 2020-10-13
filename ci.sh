#!/bin/bash

set -ex -o pipefail

# Log some general info about the environment
env | sort

if [ "$JOB_NAME" = "" ]; then
    if [ "$SYSTEM_JOBIDENTIFIER" != "" ]; then
        # azure pipelines
        JOB_NAME="$SYSTEM_JOBDISPLAYNAME"
    else
        JOB_NAME="${TRAVIS_OS_NAME}-${TRAVIS_PYTHON_VERSION:-unknown}"
    fi
fi

# Curl's built-in retry system is not very robust; it gives up on lots of
# network errors that we want to retry on. Wget might work better, but it's
# not installed on azure pipelines's windows boxes. So... let's try some good
# old-fashioned brute force. (This is also a convenient place to put options
# we always want, like -f to tell curl to give an error if the server sends an
# error response, and -L to follow redirects.)
function curl-harder() {
    for BACKOFF in 0 1 2 4 8 15 15 15 15; do
        sleep $BACKOFF
        if curl -fL --connect-timeout 5 "$@"; then
            return 0
        fi
    done
    return 1
}

################################################################
# Bootstrap python environment, if necessary
################################################################

### Azure pipelines + Windows ###

# On azure pipeline's windows VMs, to get reasonable performance, we need to
# jump through hoops to avoid touching the C:\ drive as much as possible.
if [ "$AGENT_OS" = "Windows_NT" ]; then
    # By default temp and cache directories are on C:\. Fix that.
    export TEMP="${AGENT_TEMPDIRECTORY}"
    export TMP="${AGENT_TEMPDIRECTORY}"
    export TMPDIR="${AGENT_TEMPDIRECTORY}"
    export PIP_CACHE_DIR="${AGENT_TEMPDIRECTORY}\\pip-cache"

    # Download and install Python from scratch onto D:\, instead of using the
    # pre-installed versions that azure pipelines provides on C:\.
    # Also use -DirectDownload to stop nuget from caching things on C:\.
    nuget install "${PYTHON_PKG}" -Version "${PYTHON_VERSION}" \
          -OutputDirectory "$PWD/pyinstall" -ExcludeVersion \
          -Source "https://api.nuget.org/v3/index.json" \
          -Verbosity detailed -DirectDownload -NonInteractive

    pydir="$PWD/pyinstall/${PYTHON_PKG}"
    export PATH="${pydir}/tools:${pydir}/tools/scripts:$PATH"

    # Fix an issue with the nuget python 3.5 packages
    # https://github.com/python-trio/trio/pull/827#issuecomment-457433940
    rm -f "${pydir}/tools/pyvenv.cfg" || true
fi

### Travis + macOS ###

if [ "$TRAVIS_OS_NAME" = "osx" ]; then
    JOB_NAME="osx_${MACPYTHON}"
    curl-harder -o macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/*/bin/
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/*/bin/python3
    # The pip in older MacPython releases doesn't support a new enough TLS
    curl-harder -o get-pip.py https://bootstrap.pypa.io/get-pip.py
    sudo $PYTHON_EXE get-pip.py
    sudo $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

### PyPy nightly (currently on Travis) ###

if [ "$PYPY_NIGHTLY_BRANCH" != "" ]; then
    JOB_NAME="pypy_nightly_${PYPY_NIGHTLY_BRANCH}"
    curl-harder -o pypy.tar.bz2 http://buildbot.pypy.org/nightly/${PYPY_NIGHTLY_BRANCH}/pypy-c-jit-latest-linux64.tar.bz2
    if [ ! -s pypy.tar.bz2 ]; then
        # We know:
        # - curl succeeded (200 response code)
        # - nonetheless, pypy.tar.bz2 does not exist, or contains no data
        # This isn't going to work, and the failure is not informative of
        # anything involving Trio.
        ls -l
        echo "PyPy3 nightly build failed to download – something is wrong on their end."
        echo "Skipping testing against the nightly build for right now."
        exit 0
    fi
    tar xaf pypy.tar.bz2
    # something like "pypy-c-jit-89963-748aa3022295-linux64"
    PYPY_DIR=$(echo pypy-c-jit-*)
    PYTHON_EXE=$PYPY_DIR/bin/pypy3

    if ! ($PYTHON_EXE -m ensurepip \
              && $PYTHON_EXE -m pip install virtualenv \
              && $PYTHON_EXE -m virtualenv testenv); then
        echo "pypy nightly is broken; skipping tests"
        exit 0
    fi
    source testenv/bin/activate
fi

################################################################
# We have a Python environment!
################################################################

python -c "import sys, struct, ssl; print('#' * 70); print('python:', sys.version); print('version_info:', sys.version_info); print('bits:', struct.calcsize('P') * 8); print('openssl:', ssl.OPENSSL_VERSION, ssl.OPENSSL_VERSION_INFO); print('#' * 70)"

python -m pip install -U pip setuptools wheel
python -m pip --version

python setup.py sdist --formats=zip
python -m pip install dist/*.zip

pypy_tag=$(python -c "import sys; print('pypy' if sys.implementation.name == 'pypy' else '')")

if [ "$CHECK_DOCS" = "1" ]; then
    python -m pip install -r docs-requirements.txt
    towncrier --yes  # catch errors in newsfragments
    cd docs
    # -n (nit-picky): warn on missing references
    # -W: turn warnings into errors
    sphinx-build -nW  -b html source build
elif [ "$CHECK_LINT" = "1" ]; then
    python -m pip install -r test-requirements.txt
    source check.sh
else
    # Actual tests
    python -m pip install -r test-requirements.txt

    if [ "$OLD_GREENLET" = "1" ]; then
        # We run some tests under a greenlet version without the contextvars bug,
        # to make sure we haven't regressed that
        python -m pip install greenlet==0.4.16
    fi

    mkdir empty
    cd empty

    INSTALLDIR=$(python -c "import os, greenback; print(os.path.dirname(greenback.__file__))")
    cp ../setup.cfg $INSTALLDIR
    if pytest -W error -ra --junitxml=../test-results.xml ${INSTALLDIR} --cov="$INSTALLDIR" --cov-config=../.coveragerc$pypy_tag --verbose; then
        PASSED=true
    else
        PASSED=false
    fi

    # Flag pypy and cpython coverage differently, until it settles down...
    FLAG="cpython"
    if [[ "$PYPY_NIGHTLY_BRANCH" == "py3.6" ]]; then
        FLAG="pypy36nightly"
    elif [[ "$(python -V)" == *PyPy* ]]; then
        FLAG="pypy36release"
    fi
    # It's more common to do
    #   bash <(curl ...)
    # but azure is broken:
    #   https://developercommunity.visualstudio.com/content/problem/743824/bash-task-on-windows-suddenly-fails-with-bash-devf.html
    curl-harder -o codecov.sh https://codecov.io/bash
    bash codecov.sh -n "${JOB_NAME}" -F "$FLAG"

    $PASSED
fi
