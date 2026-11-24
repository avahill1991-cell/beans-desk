"""Windowed entry point for the packaged desktop build.

PyInstaller needs a script, not `python -m`, so this exists only to be that script.
"""

from beansdesk.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
