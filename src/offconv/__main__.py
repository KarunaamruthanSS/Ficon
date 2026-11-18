"""Lets the tool run as `python -m offconv`."""

import sys

from offconv.cli import main

if __name__ == "__main__":
    sys.exit(main())
