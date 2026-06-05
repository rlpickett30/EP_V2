# ============================================================
# database_config.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Database
#
# Role:
#   Configuration Helper
#
# Purpose:
#   Define stable database archive paths and SQLite defaults.
#
# Expected config source:
#   None
#
# Expected config section:
#   None
#
# Does:
#   - Defines the database subsystem root path
#   - Defines the database data directory
#   - Defines the SQLite archive file path
#   - Defines basic SQLite connection defaults
#
# Does NOT:
#   - Open the database connection
#   - Create database tables
#   - Write database records
#   - Store runtime state
#
# Owner:
#   database_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

from pathlib import Path


# ============================================================
# PATH DEFINITIONS
# ============================================================

DATABASE_ROOT_DIR = Path(
    __file__
).resolve().parent

DATABASE_DATA_DIR = DATABASE_ROOT_DIR / "data"

DATABASE_FILE_NAME = "enviro_pulse_archive.db"

DATABASE_PATH = DATABASE_DATA_DIR / DATABASE_FILE_NAME


# ============================================================
# SQLITE SETTINGS
# ============================================================

DATABASE_TIMEOUT_SECONDS = 30

ENABLE_FOREIGN_KEYS = True

ENABLE_WRITE_AHEAD_LOGGING = True


# ============================================================
# PUBLIC API
# ============================================================

def ensure_database_directories():
    """
    Ensures that the database data directory exists.

    This does not create the SQLite database file directly.
    SQLite creates the file when the first connection is opened.
    """

    DATABASE_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )