"""Entry point: `python -m local_pdf_translator`."""

import sys

from .ui.app import main

if __name__ == "__main__":
    sys.exit(main())
