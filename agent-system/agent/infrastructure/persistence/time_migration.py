"""一次性将时间表示转换为北京时间；不平移事件实际发生的时间。"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from ...common.models import as_beijing, beijing_now, beijing_record_times


TIME_COLUMNS = {
    "characters": ("created_at",),
    "conversations": ("created_at",),
    "messages": ("created_at",),
    "memories": ("created_at", "expires_at"),
    "memory_retention": ("anchor_at", "last_recalled_at"),
    "turns": ("started_at", "finished_at"),
    "events": ("created_at",),
}


def migrate_beijing_time(connection, path):
    marker = connection.execute("SELECT value FROM runtime_settings WHERE key='timestamp_timezone'").fetchone()
    if marker and marker[0] == "Asia/Shanghai":
        return
    backup = path.with_name(f"{path.stem}.before_beijing_{beijing_now():%Y%m%d_%H%M%S_%f}.sqlite3")
    with closing(sqlite3.connect(backup)) as target:
        connection.backup(target)

    # 备份完成再开始写事务。任一字段无法转换，整个迁移回滚。
    connection.execute("BEGIN IMMEDIATE")
    for table, columns in TIME_COLUMNS.items():
        for row in connection.execute(f"SELECT rowid AS migration_row, {','.join(columns)} FROM {table}").fetchall():
            changes = {column: as_beijing(datetime.fromisoformat(row[column])).isoformat()
                       for column in columns if row[column] is not None}
            if changes:
                connection.execute(f"UPDATE {table} SET " + ",".join(f"{column}=?" for column in changes)
                                   + " WHERE rowid=?", (*changes.values(), row["migration_row"]))

    for table in ("character_states", "emotion_states", "events"):
        for row in connection.execute(f"SELECT rowid AS migration_row,payload_json FROM {table}").fetchall():
            payload = beijing_record_times(json.loads(row["payload_json"]))
            connection.execute(f"UPDATE {table} SET payload_json=? WHERE rowid=?",
                               (json.dumps(payload, ensure_ascii=False), row["migration_row"]))
    connection.execute("INSERT INTO runtime_settings(key,value) VALUES ('timestamp_timezone','Asia/Shanghai') "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
