"""Entry point: `python -m local_pdf_translator`, and the frozen executable.

The import is absolute rather than relative on purpose. PyInstaller runs this
file as the top-level script, where there is no parent package, so
`from .ui.app import main` fails at startup with "attempted relative import
with no known parent package". The absolute form works both ways.
"""

import sys

from local_pdf_translator.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
