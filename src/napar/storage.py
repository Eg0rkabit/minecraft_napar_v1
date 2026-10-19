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
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(goals)')}
        if 'success_check' not in columns:
            self.db.execute('ALTER TABLE goals ADD COLUMN success_check TEXT')
        for name, definition in [('parent_id', 'TEXT'), ('priority', 'INTEGER DEFAULT 5')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE goals ADD COLUMN {name} {definition}')
        memory_columns = {row[1] for row in self.db.execute('PRAGMA table_info(memories)')}
        for name, definition in [('confidence', 'REAL DEFAULT 0.35'), ('truth', "TEXT DEFAULT 'hypothesis'"),
                                 ('source', "TEXT DEFAULT ''"), ('verified', 'TEXT')]:
            if name not in memory_columns:
                self.db.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS runtime_flags(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS memory_history(id INTEGER PRIMARY KEY,world TEXT,key TEXT,payload TEXT,replaced TEXT);
            CREATE TABLE IF NOT EXISTS dialogue(id INTEGER PRIMARY KEY,world TEXT,role TEXT,text TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS preferences(world TEXT PRIMARY KEY,autonomy TEXT DEFAULT 'normal');
            CREATE TABLE IF NOT EXISTS observations(world TEXT,dimension TEXT,position TEXT,payload TEXT,verified TEXT,PRIMARY KEY(world,dimension,position));
        ''')
        columns={row[1] for row in self.db.execute('PRAGMA table_info(preferences)')}
        if 'presence' not in columns:
            self.db.execute("ALTER TABLE preferences ADD COLUMN presence TEXT DEFAULT 'auto'")
        self.db.execute("UPDATE goals SET status='paused',summary='[revalidate] Brain restarted; verify current world before resuming' WHERE status='active'")
        self.db.commit()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def close(self):
        self.db.close()

    def remember(self, world, **data):
        old = self.db.execute('SELECT * FROM memories WHERE world=? AND key=?', (world,data['key'])).fetchone()
        if old and (old['content'] != data['content'] or old['evidence'] != data['evidence']):
            self.db.execute('INSERT INTO memory_history(world,key,payload,replaced) VALUES(?,?,?,?)',
                            (world,data['key'],json.dumps(dict(old),ensure_ascii=False),self.now()))
        truth=data.get('truth','hypothesis')
        verified=self.now() if truth in ('observation','owner_statement') else None
        self.db.execute("""INSERT INTO memories(world,key,content,kind,evidence,updated,confidence,truth,source,verified) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(world,key) DO UPDATE SET content=excluded.content,
            kind=excluded.kind,evidence=excluded.evidence,updated=excluded.updated,
            confidence=excluded.confidence,truth=excluded.truth,source=excluded.source,verified=excluded.verified""",
            (world, data['key'], data['content'], data['kind'], data['evidence'], self.now(),
             data.get('confidence',0.5),truth,data.get('source',''),verified))
        self.db.execute('DELETE FROM memory_history WHERE id <= (SELECT COALESCE(MAX(id),0)-5000 FROM memory_history)')
        self.db.commit()
        return {'key': data['key'], 'saved': True, 'replaced_previous': bool(old), 'truth':truth}

    def recall(self, world, query='', limit=12):
        # Escape LIKE metacharacters so a model cannot turn a query into a wildcard dump.
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        rows = self.db.execute("""SELECT key,content,kind,evidence,updated,confidence,truth,source,verified FROM memories
            WHERE world=? AND (key LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')
            ORDER BY updated DESC LIMIT ?""", (world, pattern, pattern, limit))
        return [dict(row) for row in rows]

    def create_goal(self, world, description, success_condition, success_check=None, parent_id=None, priority=5):
        if parent_id and not self.db.execute('SELECT 1 FROM goals WHERE world=? AND id=?',(world,parent_id)).fetchone():
            raise ValueError('Parent goal does not exist in this world')
        goal_id = str(uuid4())
        self.db.execute('INSERT INTO goals(id,world,description,success_condition,status,summary,updated,success_check,parent_id,priority) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (goal_id, world, description, success_condition, 'active', '', self.now(),
                         json.dumps(success_check) if success_check else None,parent_id,priority))
        self.db.commit()
        return {'goal_id': goal_id, 'status': 'active'}

    def goal_check(self, world, goal_id):
        row = self.db.execute('SELECT success_check FROM goals WHERE id=? AND world=?',(goal_id,world)).fetchone()
        if not row or not row[0]:
            raise ValueError('This goal has no verifiable success check; completion is not confirmed')
        return json.loads(row[0])

    def update_goal(self, world, goal_id, status, summary):
        if status=='completed' and self.db.execute("SELECT 1 FROM goals WHERE world=? AND parent_id=? AND status NOT IN ('completed','failed')",(world,goal_id)).fetchone():
            raise ValueError('Finish or resolve child goals before completing the parent')
        cursor = self.db.execute('UPDATE goals SET status=?,summary=?,updated=? WHERE id=? AND world=?',
                                 (status, summary, self.now(), goal_id, world))
        self.db.commit()
        if not cursor.rowcount:
            raise ValueError('Goal does not exist in this world')
        return {'goal_id': goal_id, 'status': status}

    def goals(self, world):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM goals WHERE world=? AND status IN ('active','paused') ORDER BY priority DESC,updated DESC LIMIT 20", (world,))]

    def pause_goals(self,world,reason):
        with self.db:
            self.db.execute("UPDATE goals SET status='paused',summary=?,updated=? WHERE world=? AND status='active'",(reason,self.now(),world))

    def autonomy(self,world,mode=None):
        if mode is not None:
            with self.db:
                self.db.execute('INSERT INTO preferences(world,autonomy) VALUES(?,?) ON CONFLICT(world) DO UPDATE SET autonomy=excluded.autonomy',(world,mode))
        row=self.db.execute('SELECT autonomy FROM preferences WHERE world=?',(world,)).fetchone()
        return row[0] if row else 'normal'

    def conversation(self,world,role=None,text=''):
        if role:
            with self.db:
                self.db.execute('INSERT INTO dialogue(world,role,text,created) VALUES(?,?,?,?)',(world,role,text[:2000],self.now()))
                self.db.execute('DELETE FROM dialogue WHERE id <= (SELECT COALESCE(MAX(id),0)-500 FROM dialogue)')
        return [dict(row) for row in self.db.execute('SELECT role,text,created FROM (SELECT * FROM dialogue WHERE world=? ORDER BY id DESC LIMIT 12) ORDER BY id',(world,))]

    def observe_blocks(self,world,dimension,blocks):
        with self.db:
            for block in blocks[:96]:
                location=json.dumps(block['position'],sort_keys=True)
                self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?) ON CONFLICT(world,dimension,position) DO UPDATE SET payload=excluded.payload,verified=excluded.verified',
                                (world,dimension,location,json.dumps(block),self.now()))
            self.db.execute('DELETE FROM observations WHERE rowid IN (SELECT rowid FROM observations ORDER BY verified DESC LIMIT -1 OFFSET 2000)')

    def world_model(self,world):
        return [dict(row) for row in self.db.execute('SELECT dimension,position,payload,verified FROM observations WHERE world=? ORDER BY verified DESC LIMIT 20',(world,))]

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
            updated = self.db.execute('UPDATE usage SET calls=calls+1 WHERE day=? AND (?=0 OR calls<?)', (day, maximum, maximum))
            if not updated.rowcount:
                raise ValueError('Daily model call limit reached (UTC); no request sent')

    def add_tokens(self, tokens):
        with self.db:
            self.db.execute('UPDATE usage SET tokens=tokens+? WHERE day=?', (tokens, self.now()[:10]))

    def usage(self):
        row = self.db.execute('SELECT * FROM usage WHERE day=?', (self.now()[:10],)).fetchone()
        return dict(row) if row else {'day': self.now()[:10], 'calls': 0, 'tokens': 0}

    def provider_pause(self, reason=None):
        if reason is not None:
            self.db.execute('INSERT OR REPLACE INTO runtime_flags VALUES(?,?)',('provider_pause',reason))
            self.db.commit()
        row=self.db.execute('SELECT value FROM runtime_flags WHERE key=?',('provider_pause',)).fetchone()
        return row['value'] if row else ''

    def presence(self,world,mode=None):
        if mode is not None:
            if mode not in ('stay','auto'):raise ValueError('Invalid presence mode')
            with self.db:
                self.db.execute('INSERT INTO preferences(world,presence) VALUES(?,?) ON CONFLICT(world) DO UPDATE SET presence=excluded.presence',(world,mode))
        row=self.db.execute('SELECT presence FROM preferences WHERE world=?',(world,)).fetchone()
        return row[0] if row else 'auto'

