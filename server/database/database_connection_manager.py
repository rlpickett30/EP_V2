# ============================================================
# database_connection_manager.py
#
# EnviroPulse V2.0
#
# Subsystem:
#   Database
#
# Role:
#   Manager
#
# Purpose:
#   Manage SQLite database connections for the EnviroPulse archive.
#
# Expected config source:
#   database_config.py
#
# Expected config section:
#   Module-level constants
#
# Does:
#   - Ensures the database data directory exists
#   - Opens SQLite database connections
#   - Applies SQLite connection settings
#   - Commits database changes
#   - Rolls back failed database changes
#   - Closes database connections
#
# Does NOT:
#   - Decide which events should be archived
#   - Create database tables
#   - Define database schema
#   - Interpret event payloads
#   - Publish events to the event bus
#
# Owner:
#   database_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from database.database_config import (
    DATABASE_PATH,
    DATABASE_TIMEOUT_SECONDS,
    ENABLE_FOREIGN_KEYS,
    ENABLE_WRITE_AHEAD_LOGGING,
    ensure_database_directories
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging
import sqlite3


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class DatabaseConnectionManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        debug: bool = False
    ):

        self.debug = debug

        ensure_database_directories()

    # ========================================================
    # PUBLIC API
    # ========================================================

    def get_connection(self):
        """
        Opens and returns a configured SQLite connection.

        The caller is responsible for closing the connection.
        """

        try:

            connection = sqlite3.connect(
                DATABASE_PATH,
                timeout=DATABASE_TIMEOUT_SECONDS
            )

            connection.row_factory = sqlite3.Row

            self._apply_connection_settings(
                connection
            )

            if self.debug:
                logging.info(
                    f"Database connection opened: {DATABASE_PATH}"
                )

            return connection

        except Exception as error:

            logging.error(
                f"Database connection failed: {error}"
            )

            raise

    def execute_write(
        self,
        query: str,
        values: tuple = ()
    ):
        """
        Executes a single write query and commits the result.

        Returns a structured result dictionary.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        connection = None

        try:

            connection = self.get_connection()

            cursor = connection.cursor()

            cursor.execute(
                query,
                values
            )

            connection.commit()

            result["success"] = True

            result["data"] = {
                "last_row_id": cursor.lastrowid,
                "rows_affected": cursor.rowcount
            }

            if self.debug:
                result["debug"] = {
                    "query": query,
                    "values": values
                }

        except Exception as error:

            if connection is not None:
                connection.rollback()

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database write failed: {error}"
            )

        finally:

            if connection is not None:
                connection.close()

        return result

    def execute_many_write(
        self,
        query: str,
        values_list: list
    ):
        """
        Executes many write queries as one committed transaction.

        This is useful later for batch archive writes.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        connection = None

        try:

            connection = self.get_connection()

            cursor = connection.cursor()

            cursor.executemany(
                query,
                values_list
            )

            connection.commit()

            result["success"] = True

            result["data"] = {
                "rows_affected": cursor.rowcount
            }

            if self.debug:
                result["debug"] = {
                    "query": query,
                    "batch_size": len(values_list)
                }

        except Exception as error:

            if connection is not None:
                connection.rollback()

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database batch write failed: {error}"
            )

        finally:

            if connection is not None:
                connection.close()

        return result

    def execute_read(
        self,
        query: str,
        values: tuple = ()
    ):
        """
        Executes a read query and returns rows as dictionaries.

        This is not for GUI live state.
        This exists for testing, debugging, and future archive queries.
        """

        result = {
            "success": False,
            "data": {
                "rows": []
            },
            "debug": {},
            "errors": []
        }

        connection = None

        try:

            connection = self.get_connection()

            cursor = connection.cursor()

            cursor.execute(
                query,
                values
            )

            rows = cursor.fetchall()

            result["success"] = True

            result["data"]["rows"] = [
                dict(row) for row in rows
            ]

            if self.debug:
                result["debug"] = {
                    "query": query,
                    "values": values,
                    "rows_returned": len(rows)
                }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database read failed: {error}"
            )

        finally:

            if connection is not None:
                connection.close()

        return result

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _apply_connection_settings(
        self,
        connection
    ):
        """
        Applies SQLite settings to a newly opened connection.
        """

        cursor = connection.cursor()

        if ENABLE_FOREIGN_KEYS:
            cursor.execute(
                "PRAGMA foreign_keys = ON;"
            )

        if ENABLE_WRITE_AHEAD_LOGGING:
            cursor.execute(
                "PRAGMA journal_mode = WAL;"
            )