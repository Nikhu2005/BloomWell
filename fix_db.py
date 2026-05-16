import sqlite3, glob, os

dbs = glob.glob('**/*.db', recursive=True)
print("Found databases:", dbs)

for db in dbs:
    print(f"\nFixing: {db}")
    con = sqlite3.connect(db)
    cur = con.cursor()
    
    # Show existing columns
    cur.execute("PRAGMA table_info(user)")
    cols = [row[1] for row in cur.fetchall()]
    print("Current columns:", cols)
    
    if 'is_verified' not in cols:
        cur.execute("ALTER TABLE user ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT 0")
        con.commit()
        print("✓ Added is_verified column")
    else:
        print("✓ Column already exists")
    
    con.close()

print("\nDone! Now run: python app.py")