"""Small durable store. World knowledge never leaks into another world."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memories (
                world TEXT, key TEXT, content TEXT, kind TEXT, evidence TEXT,
                updated TEXT, PRIMARY KEY(world,key));
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY, world TEXT, description TEXT,
                success_condition TEXT, status TEXT, summary TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, world TEXT, kind TEXT, payload TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS usage (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL, tokens INTEGER NOT NULL);
        """)
        # Revalidate a plan against a fresh world after every process restart.
        self.db.execute("UPDATE goals SET status='paused' WHERE status='active'")
        self.db.commit()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def close(self):
        self.db.close()

    def remember(self, world, **data):
        self.db.execute("""INSERT INTO memories VALUES(?,?,?,?,?,?)
            ON CONFLICT(world,key) DO UPDATE SET content=excluded.content,
            kind=excluded.kind,evidence=excluded.evidence,updated=excluded.updated""",
            (world, data['key'], data['content'], data['kind'], data['evidence'], self.now()))
        self.db.commit()
        return {'key': data['key'], 'saved': True}

    def recall(self, world, query='', limit=12):
        # Escape LIKE metacharacters so a model cannot turn a query into a wildcard dump.
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        rows = self.db.execute("""SELECT key,content,kind,evidence,updated FROM memories
            WHERE world=? AND (key LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')
            ORDER BY updated DESC LIMIT ?""", (world, pattern, pattern, limit))
        return [dict(row) for row in rows]

    def create_goal(self, world, description, success_condition):
        goal_id = str(uuid4())
        self.db.execute('INSERT INTO goals VALUES(?,?,?,?,?,?,?,?)',
                        (goal_id, world, description, success_condition, 'active', '', self.now()))
        self.db.commit()
        return {'goal_id': goal_id, 'status': 'active'}

    def update_goal(self, world, goal_id, status, summary):
        cursor = self.db.execute('UPDATE goals SET status=?,summary=?,updated=? WHERE id=? AND world=?',
                                 (status, summary, self.now(), goal_id, world))
        self.db.commit()
        if not cursor.rowcount:
            raise ValueError('Goal does not exist in this world')
        return {'goal_id': goal_id, 'status': status}

    def goals(self, world):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM goals WHERE world=? AND status IN ('active','paused') ORDER BY updated DESC LIMIT 20", (world,))]

    def audit(self, world, kind, payload):
        self.db.execute('INSERT INTO audit(world,kind,payload,created) VALUES(?,?,?,?)',
                        (world, kind, json.dumps(payload, ensure_ascii=False), self.now()))
        self.db.execute('DELETE FROM audit WHERE id <= (SELECT COALESCE(MAX(id),0)-5000 FROM audit)')
        self.db.commit()

    def recent(self, world, limit=10):
        return [dict(r) for r in self.db.execute(
            'SELECT kind,payload,created FROM audit WHERE world=? ORDER BY id DESC LIMIT ?', (world, limit))]

    def reserve_call(self, maximum):
        day = self.now()[:10]
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO usage VALUES(?,0,0)', (day,))
            updated = self.db.execute('UPDATE usage SET calls=calls+1 WHERE day=? AND calls<?', (day, maximum))
            if not updated.rowcount:
                raise ValueError('Daily model call limit reached (UTC); no request sent')

    def add_tokens(self, tokens):
        with self.db:
            self.db.execute('UPDATE usage SET tokens=tokens+? WHERE day=?', (tokens, self.now()[:10]))

    def usage(self):
        row = self.db.execute('SELECT * FROM usage WHERE day=?', (self.now()[:10],)).fetchone()
        return dict(row) if row else {'day': self.now()[:10], 'calls': 0, 'tokens': 0}
