#!/bin/bash

set -ex

EXIT_STATUS=0

# Autoformatter *first*, to avoid double-reporting errors
black --check setup.py greenback \
    || EXIT_STATUS=$?

# Run flake8 without pycodestyle and import-related errors
flake8 greenback/ \
    --ignore=D,E,W,F401,F403,F405,F821,F822\
    || EXIT_STATUS=$?

# Uncomment to run mypy (to check static typing)
mypy --strict -p greenback || EXIT_STATUS=$?

# Finally, leave a really clear warning of any issues and exit
if [ $EXIT_STATUS -ne 0 ]; then
    cat <<EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Problems were found by static analysis (listed above).
To fix formatting and see remaining errors, run

    pip install -r test-requirements.txt
    black setup.py greenback
    ./check.sh

in your local checkout.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
    exit 1
fi
exit 0
