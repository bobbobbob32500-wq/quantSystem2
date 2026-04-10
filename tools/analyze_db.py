import sqlite3
import os

def analyze_db(db_path, label):
    if not os.path.exists(db_path):
        print(f"{label}: not found")
        return
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    print(f"\n{'='*60}")
    print(f"{label} ({size_mb:.2f} MB)")
    print(f"{'='*60}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"Tables ({len(tables)}): {tables}")

    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM '{t}'")
            cnt = cursor.fetchone()[0]
            cursor.execute(f"PRAGMA table_info('{t}')")
            cols = [c[1] for c in cursor.fetchall()]
            cursor.execute(f"PRAGMA index_list('{t}')")
            indexes = cursor.fetchall()
            print(f"  {t}: {cnt:,} rows | cols: {cols} | indexes: {len(indexes)}")
            for idx in indexes:
                cursor.execute(f"PRAGMA index_info('{idx[1]}')")
                idx_cols = [i[2] for i in cursor.fetchall()]
                print(f"    index [{idx[1]}]: {idx_cols}")
        except Exception as e:
            print(f"  {t}: ERROR {e}")

    # PRAGMA stats
    cursor.execute("PRAGMA page_count")
    page_count = cursor.fetchone()[0]
    cursor.execute("PRAGMA page_size")
    page_size = cursor.fetchone()[0]
    cursor.execute("PRAGMA freelist_count")
    freelist = cursor.fetchone()[0]
    total_pages = page_count
    free_ratio = freelist / total_pages if total_pages > 0 else 0
    print(f"\n  page_count={page_count}, page_size={page_size}B, freelist={freelist} ({free_ratio*100:.1f}% waste)")
    conn.close()

analyze_db('data/database/quant_system.db', 'quant_system')
analyze_db('data/history_recommendation.db', 'history_recommendation')
