We mostly follow the Trio contributing guide:
    https://trio.readthedocs.io/en/latest/contributing.html
but (this being largely a personal project) contributors will not automatically get commit
bits, and we're trying out some alternative tooling (code formatting with `black` and
enforced static type checking to pass `mypy --strict`) compared to the mainline Trio
projects. `greenback` might move to live under the python-trio Github organization
once its scope has stabilized a bit.
