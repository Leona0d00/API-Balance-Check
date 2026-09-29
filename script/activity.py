"""Read only OpenCode response metadata; never load prompts or credentials."""
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import closing

ALIASES = {'opencode-go': 'opencode_go', 'opencode': 'opencode_zen', 'zhipuai': 'zhipu', 'google': 'gemini', 'moonshotai': 'moonshot'}


def default_database():
    configured = os.environ.get('API_BALANCE_OPENCODE_DB')
    if configured:
        return Path(configured)
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'opencode/opencode.db'


def load_activity(path=None, now=None):
    path = Path(path) if path else default_database()
    now = now or datetime.now()
    dates = [(now.date() - timedelta(days=6-i)).isoformat() for i in range(7)]
    result = {'providers': {}, 'dates': dates, 'source': str(path), 'status': 'missing', 'updated_at': now.isoformat(timespec='seconds')}
    if not path.is_file():
        return result
    cutoff = int(datetime.combine(now.date() - timedelta(days=6), datetime.min.time()).timestamp() * 1000)
    deadline = time.monotonic() + 8
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 5000)
            # Only specific scalar response metadata is selected. No message text/parts.
            rows = db.execute("""
                SELECT json_extract(data,'$.providerID'), json_extract(data,'$.modelID'),
                       json_extract(data,'$.time.completed'),
                       coalesce(json_extract(data,'$.tokens.input'),0) + coalesce(json_extract(data,'$.tokens.output'),0)
                       + coalesce(json_extract(data,'$.tokens.reasoning'),0) + coalesce(json_extract(data,'$.tokens.cache.read'),0)
                       + coalesce(json_extract(data,'$.tokens.cache.write'),0), coalesce(json_extract(data,'$.cost'),0)
                FROM message WHERE json_valid(data) AND json_extract(data,'$.role')='assistant'
                    AND json_extract(data,'$.error') IS NULL AND json_extract(data,'$.time.completed') IS NOT NULL
            """).fetchall()
        for provider, model, stamp, tokens, cost in rows:
            if not provider or int(stamp) > int(now.timestamp()*1000):
                continue
            provider = ALIASES.get(provider, provider)
            item = result['providers'].setdefault(provider, {'calls': 0, 'tokens': 0, 'cost': 0, 'daily': [0]*7, 'last_at': 0, 'models': {}})
            item['last_at'] = max(item['last_at'], int(stamp))
            if int(stamp) < cutoff:
                continue
            day = datetime.fromtimestamp(int(stamp)/1000).date().isoformat()
            if day not in dates:
                continue
            item['calls'] += 1
            item['tokens'] += int(tokens)
            item['cost'] += float(cost)
            item['daily'][dates.index(day)] += 1
            item['models'][model or 'unknown'] = item['models'].get(model or 'unknown', 0) + 1
        result['status'] = 'ready'
    except (sqlite3.Error, ValueError, TypeError, OverflowError, OSError) as exc:
        result['status'] = 'error'
        result['error'] = str(exc)
    return result
