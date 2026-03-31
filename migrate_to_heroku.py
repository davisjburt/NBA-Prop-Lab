import os
import sqlite3
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = "instance/prop_lab.db"
HEROKU_URL = os.getenv("DATABASE_URL")
if not HEROKU_URL:
    raise RuntimeError("DATABASE_URL is not set")

TABLE_ORDER = [
    "players",
    "player_game_stats",
    "model_prop_eval",
    "model_moneyline_eval",
]

BOOLEAN_COLUMNS = {
    "model_moneyline_eval": {"correct"},
    "model_prop_eval": {"correct"},
}

def convert_row(table, columns, row):
    converted = []
    bool_cols = BOOLEAN_COLUMNS.get(table, set())

    for col, val in zip(columns, row):
        if col in bool_cols and val is not None:
            converted.append(bool(val))
        else:
            converted.append(val)

    return tuple(converted)

def migrate():
    print("🔌 Connecting to SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    print("🔌 Connecting to Heroku Postgres...")
    pg_conn = psycopg2.connect(HEROKU_URL, sslmode="require")
    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    for table in TABLE_ORDER:
        print(f"⏳ Migrating table: {table}")

        sqlite_cur.execute(f'SELECT * FROM "{table}"')
        rows = sqlite_cur.fetchall()

        if not rows:
            print("   ⚠️ Empty — skipping\n")
            continue

        total_rows = len(rows)
        print(f"   ℹ️ {total_rows} rows to migrate")

        columns = [desc[0] for desc in sqlite_cur.description]

        truncate_sql = sql.SQL(
            "TRUNCATE TABLE {} RESTART IDENTITY CASCADE"
        ).format(sql.Identifier(table))

        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() * len(columns)),
        )

        try:
            pg_cur.execute(truncate_sql)

            inserted = 0
            last_percent = -1

            for idx, row in enumerate(rows, start=1):
                converted_row = convert_row(table, columns, tuple(row))
                pg_cur.execute(insert_sql, converted_row)
                inserted += 1

                # progress within this table
                percent = int(idx * 100 / total_rows)
                if percent % 10 == 0 and percent != last_percent:
                    print(f"   🔃 {percent}% complete for {table}")
                    last_percent = percent

            pg_conn.commit()
            print(f"   ✅ {inserted} rows inserted for {table}\n")

        except Exception as e:
            pg_conn.rollback()
            print(f"   ❌ Error migrating {table}: {e}\n")

    sqlite_conn.close()
    pg_conn.close()
    print("🏁 Migration complete!")

if __name__ == "__main__":
    migrate()