"""Application metadata — version and copyright."""

APP_NAME = "Lithophane Keychain Generator"
__version__ = "2.0"
REV = f"Rev {__version__}"

COPYRIGHT_OWNER = "NovaForge Innovations LLC"
COPYRIGHT_YEAR = "2026"
COPYRIGHT = f"Copyright © {COPYRIGHT_YEAR} {COPYRIGHT_OWNER}. All rights reserved."

ABOUT_TEXT = (
    f"{APP_NAME}\n"
    f"{REV}\n\n"
    f"{COPYRIGHT}\n\n"
    "Print modes:\n"
    "  • White Lithophane → STL\n"
    "  • 4-Color Lithophane (CMYW) → 3MF\n"
    "      Cyan（青）+ Magenta（洋红）+ Yellow（黄）+ White（白）\n"
    "  • Color Layer Art → 3MF (AMS)\n\n"
    "Photo → keychain for Bambu Studio."
)
