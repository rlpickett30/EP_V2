# ============================================================
# database_schema_manager.py
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
#   Create and verify the SQLite schema for the EnviroPulse archive.
#
# Expected config source:
#   database_config.py
#
# Expected config section:
#   Module-level constants
#
# Does:
#   - Creates required database archive tables
#   - Creates useful indexes for future searching
#   - Verifies that the database schema exists
#
# Does NOT:
#   - Decide which events should be archived
#   - Write event records
#   - Interpret event payloads
#   - Maintain live system state
#   - Publish events to the event bus
#
# Owner:
#   database_dispatcher.py
#
# ============================================================

# ============================================================
# IMPORT DEFINITIONS FROM OTHER ENVIROPULSE SCRIPTS
# ============================================================

from database.database_connection_manager import (
    DatabaseConnectionManager
)


# ============================================================
# IMPORT SUPPORT LIBRARIES
# ============================================================

import logging


# ============================================================
# CLASS DEFINITIONS
# ============================================================

class DatabaseSchemaManager:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        debug: bool = False
    ):

        self.connection_manager = connection_manager
        self.debug = debug

    # ========================================================
    # PUBLIC API
    # ========================================================

    def initialize_schema(self):
        """
        Creates all required database tables and indexes.

        This method is safe to run every time the server starts.
        Existing tables are not deleted or overwritten.
        """

        result = {
            "success": False,
            "data": {},
            "debug": {},
            "errors": []
        }

        connection = None

        try:

            connection = self.connection_manager.get_connection()

            cursor = connection.cursor()

            cursor.executescript(
                self._get_schema_script()
            )

            connection.commit()

            result["success"] = True

            result["data"] = {
                "schema_initialized": True
            }

            if self.debug:
                result["debug"] = {
                    "tables": self._get_expected_tables()
                }

            logging.info(
                "Database schema initialized."
            )

        except Exception as error:

            if connection is not None:
                connection.rollback()

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database schema initialization failed: {error}"
            )

        finally:

            if connection is not None:
                connection.close()

        return result

    def verify_schema(self):
        """
        Checks whether the expected archive tables exist.
        """

        result = {
            "success": False,
            "data": {
                "missing_tables": [],
                "existing_tables": []
            },
            "debug": {},
            "errors": []
        }

        try:

            query = """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table';
            """

            read_result = self.connection_manager.execute_read(
                query
            )

            if not read_result["success"]:

                result["errors"].extend(
                    read_result["errors"]
                )

                return result

            existing_tables = [
                row["name"]
                for row in read_result["data"]["rows"]
            ]

            expected_tables = self._get_expected_tables()

            missing_tables = [
                table
                for table in expected_tables
                if table not in existing_tables
            ]

            result["success"] = len(missing_tables) == 0

            result["data"] = {
                "missing_tables": missing_tables,
                "existing_tables": existing_tables
            }

            if self.debug:
                result["debug"] = {
                    "expected_tables": expected_tables
                }

        except Exception as error:

            result["errors"].append(
                str(error)
            )

            logging.error(
                f"Database schema verification failed: {error}"
            )

        return result

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _get_expected_tables(self):
        """
        Returns the required V2.0 archive table names.
        """

        return [
            "events",
            "avis_detections",
            "weather_records",
            "telemetry_records",
            "node_registry_archive",
            "system_logs"
        ]

    def _get_schema_script(self):
        """
        Returns the SQLite schema creation script.

        All raw event packages are stored as JSON text.
        Specialized tables extract important fields for future research.
        """

        return """
        -- ====================================================
        -- MASTER EVENT ARCHIVE
        -- ====================================================

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_id TEXT,
            event_type TEXT,
            event_category TEXT,

            source_subsystem TEXT,
            source_node_id TEXT,

            received_at_utc TEXT NOT NULL,
            archived_at_utc TEXT NOT NULL,

            raw_event_json TEXT NOT NULL,

            parsed_successfully INTEGER DEFAULT 1,
            parser_notes TEXT
        );


        -- ====================================================
        -- AVIS / BIRDNET DETECTIONS
        -- ====================================================

        CREATE TABLE IF NOT EXISTS avis_detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_archive_id INTEGER,

            event_id TEXT,
            node_id TEXT,

            detection_time_utc TEXT,
            common_name TEXT,
            scientific_name TEXT,

            confidence REAL,
            confidence_bin INTEGER,

            latitude REAL,
            longitude REAL,
            altitude_m REAL,

            raw_event_json TEXT NOT NULL,

            FOREIGN KEY (event_archive_id)
                REFERENCES events(id)
        );


        -- ====================================================
        -- WEATHER RECORDS
        -- ====================================================

        CREATE TABLE IF NOT EXISTS weather_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_archive_id INTEGER,

            event_id TEXT,
            node_id TEXT,

            measurement_time_utc TEXT,

            temperature_c REAL,
            humidity_percent REAL,
            dew_point_c REAL,
            pressure_hpa REAL,

            wind_speed_mps REAL,
            wind_direction_deg REAL,

            latitude REAL,
            longitude REAL,
            altitude_m REAL,

            raw_event_json TEXT NOT NULL,

            FOREIGN KEY (event_archive_id)
                REFERENCES events(id)
        );


        -- ====================================================
        -- TELEMETRY RECORDS
        -- ====================================================

        CREATE TABLE IF NOT EXISTS telemetry_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_archive_id INTEGER,

            event_id TEXT,
            node_id TEXT,

            telemetry_time_utc TEXT,

            battery_voltage REAL,
            battery_percent REAL,

            gps_locked INTEGER,
            pps_locked INTEGER,

            wifi_connected INTEGER,
            lora_connected INTEGER,

            cpu_temperature_c REAL,
            disk_free_mb REAL,
            memory_free_mb REAL,

            raw_event_json TEXT NOT NULL,

            FOREIGN KEY (event_archive_id)
                REFERENCES events(id)
        );


        -- ====================================================
        -- NODE REGISTRY ARCHIVE
        -- ====================================================

        CREATE TABLE IF NOT EXISTS node_registry_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_archive_id INTEGER,

            event_id TEXT,
            node_id TEXT,

            registry_action TEXT,
            registered_at_utc TEXT,
            archived_at_utc TEXT NOT NULL,

            node_name TEXT,
            node_role TEXT,
            hardware_version TEXT,
            firmware_version TEXT,

            latitude REAL,
            longitude REAL,
            altitude_m REAL,

            raw_event_json TEXT NOT NULL,

            FOREIGN KEY (event_archive_id)
                REFERENCES events(id)
        );


        -- ====================================================
        -- SYSTEM LOGS
        -- ====================================================

        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_archive_id INTEGER,

            event_id TEXT,

            log_time_utc TEXT NOT NULL,
            level TEXT NOT NULL,
            source_subsystem TEXT,
            message TEXT NOT NULL,

            raw_event_json TEXT,

            FOREIGN KEY (event_archive_id)
                REFERENCES events(id)
        );


        -- ====================================================
        -- INDEXES
        -- ====================================================

        CREATE INDEX IF NOT EXISTS idx_events_event_id
            ON events(event_id);

        CREATE INDEX IF NOT EXISTS idx_events_type
            ON events(event_type);

        CREATE INDEX IF NOT EXISTS idx_events_received_at
            ON events(received_at_utc);

        CREATE INDEX IF NOT EXISTS idx_events_source_node
            ON events(source_node_id);

        CREATE INDEX IF NOT EXISTS idx_avis_node_time
            ON avis_detections(node_id, detection_time_utc);

        CREATE INDEX IF NOT EXISTS idx_avis_common_name
            ON avis_detections(common_name);

        CREATE INDEX IF NOT EXISTS idx_weather_node_time
            ON weather_records(node_id, measurement_time_utc);

        CREATE INDEX IF NOT EXISTS idx_telemetry_node_time
            ON telemetry_records(node_id, telemetry_time_utc);

        CREATE INDEX IF NOT EXISTS idx_node_registry_node_id
            ON node_registry_archive(node_id);

        CREATE INDEX IF NOT EXISTS idx_system_logs_time
            ON system_logs(log_time_utc);

        CREATE INDEX IF NOT EXISTS idx_system_logs_level
            ON system_logs(level);
        """

