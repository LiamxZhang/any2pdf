import sqlite3
from datetime import datetime, timezone


class History:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, outdir TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', output TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL, elapsed REAL NOT NULL DEFAULT 0)''')
        self.db.execute("UPDATE tasks SET status='failed', error_code='interrupted' WHERE status IN ('queued','running')")
        self.db.commit()

    def add(self, source, outdir):
        cursor = self.db.execute('INSERT INTO tasks (source,outdir,created) VALUES (?,?,?)',
                                 (str(source), str(outdir), datetime.now(timezone.utc).isoformat()))
        self.db.commit()
        return cursor.lastrowid

    def update(self, task, **fields):
        allowed = {'status', 'output', 'error_code', 'detail', 'elapsed', 'outdir'}
        if not fields or not set(fields).issubset(allowed):
            raise ValueError('Invalid history fields')
        self.db.execute('UPDATE tasks SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?',
                        (*fields.values(), task))
        self.db.commit()

    def list(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM tasks ORDER BY id DESC')]

    def delete_finished(self, task):
        cursor = self.db.execute("DELETE FROM tasks WHERE id=? AND status NOT IN ('queued','running')", (task,))
        self.db.commit()
        return cursor.rowcount == 1

    def clear_finished(self):
        deleted = [row[0] for row in self.db.execute("SELECT id FROM tasks WHERE status NOT IN ('queued','running')")]
        self.db.execute("DELETE FROM tasks WHERE status NOT IN ('queued','running')")
        self.db.commit()
        return deleted

    def close(self):
        self.db.close()
