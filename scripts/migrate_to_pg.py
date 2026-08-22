#!/usr/bin/env python3
"""Sanl → PostgreSQL 迁移导出/导入工具（附录：优化 #8）

用法：
  # 1) 从 SQLite 导出为 JSON 中间格式
  python3 scripts/migrate_to_pg.py export --sqlite data/nodes.db --out /tmp/sanl_export.json

  # 2) 导入到 PostgreSQL（需 psycopg2 或 psycopg[binary]，先建好空库）
  python3 scripts/migrate_to_pg.py import --pg "postgresql://user:pass@localhost:5432/sanl" \
      --dump /tmp/sanl_export.json

说明：
- 节点数破 5 万、写锁成为瓶颈时再迁移；日常规模（<1万）SQLite WAL 已足够。
- 迁移保留全部业务表数据；自增序列在导入后自动重置。
"""
import argparse
import json
import os
import sqlite3
import sys

TABLES = [
    # (表名, 主键列) —— 按依赖顺序，sources 先于 nodes
    ("sources", "id"),
    ("nodes", "id"),
    ("check_jobs", "id"),
    ("users", "id"),
    ("tokens", "id"),
    ("cf_scan_results", "id"),
    ("cf_endpoints", "id"),
    ("node_health_history", "id"),
    ("sub_access_log", "id"),
]


def do_export(sqlite_path: str, out_path: str):
    if not os.path.exists(sqlite_path):
        sys.exit(f"SQLite 文件不存在: {sqlite_path}")
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    dump = {"meta": {"source": os.path.abspath(sqlite_path)}, "tables": {}}
    for table, _pk in TABLES:
        try:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
            dump["tables"][table] = rows
            print(f"  {table}: {len(rows)} 行")
        except sqlite3.OperationalError as e:
            print(f"  {table}: 跳过（{e}）")
    conn.close()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, default=str)
    print(f"✅ 已导出 → {out_path}")


PG_TYPES = {
    "INTEGER": "BIGINT", "REAL": "DOUBLE PRECISION", "TEXT": "TEXT",
}


def do_import(pg_dsn: str, dump_path: str, truncate: bool = False):
    try:
        import psycopg2
    except ImportError:
        sys.exit("需要 psycopg2: pip install 'psycopg2-binary'")
    with open(dump_path, encoding="utf-8") as f:
        dump = json.load(f)

    conn = psycopg2.connect(pg_dsn)
    conn.autocommit = False
    cur = conn.cursor()
    total = 0
    for table, pk in TABLES:
        rows = dump.get("tables", {}).get(table)
        if not rows:
            continue
        if truncate:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        cols = list(rows[0].keys())
        col_types = []
        for c in cols:
            sample = next((r[c] for r in rows if r[c] is not None), None)
            if isinstance(sample, int):
                col_types.append("BIGINT")
            elif isinstance(sample, float):
                col_types.append("DOUBLE PRECISION")
            else:
                col_types.append("TEXT")
        # 建表（如不存在）
        pk_decl = f", PRIMARY KEY ({pk})" if pk in cols else ""
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{c} {t}' for c, t in zip(cols, col_types))}{pk_decl})"
        )
        # 批量插入
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
        total += len(rows)
        print(f"  {table}: {len(rows)} 行导入")
        # 重置序列
        if pk in cols:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{pk}'), COALESCE((SELECT MAX({pk}) FROM {table}), 1))"
            )
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 迁移完成，共 {total} 行")


def main():
    ap = argparse.ArgumentParser(description="Sanl SQLite→PostgreSQL 迁移工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--sqlite", default="data/nodes.db")
    e.add_argument("--out", default="/tmp/sanl_export.json")
    i = sub.add_parser("import")
    i.add_argument("--pg", required=True, help="PostgreSQL DSN")
    i.add_argument("--dump", default="/tmp/sanl_export.json")
    i.add_argument("--truncate", action="store_true", help="导入前清空目标表")
    args = ap.parse_args()
    if args.cmd == "export":
        do_export(args.sqlite, args.out)
    else:
        do_import(args.pg, args.dump, args.truncate)


if __name__ == "__main__":
    main()
