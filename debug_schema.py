import sqlite3

def check_db():
    try:
        conn = sqlite3.connect('test.db')
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        print("Users table columns:")
        for col in columns:
            print(col)
        conn.close()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_db()
