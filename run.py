"""Entry point used by PyInstaller to build the single file program.

The real work is in offconv.cli; this exists because PyInstaller wants a
script to start from.
"""

import sys

from offconv.cli import main

if __name__ == "__main__":
    sys.exit(main())
