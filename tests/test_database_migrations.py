"""
Unit tests for safe database migration execution and idempotency.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from productivity_hub.database.migrations import run_migrations


class TestDatabaseMigrations(unittest.IsolatedAsyncioTestCase):
    async def test_migration_idempotency(self):
        with TemporaryDirectory() as tmp_dir:
            db_file = str(Path(tmp_dir) / "test_app.sqlite3")

            # First migration run -> version 2
            v1 = await run_migrations(db_file)
            self.assertEqual(v1, 2)

            # Re-run migration -> must complete smoothly and return version 2 without error
            v2 = await run_migrations(db_file)
            self.assertEqual(v2, 2)


if __name__ == "__main__":
    unittest.main()
