import sqlite3

conn = sqlite3.connect("database.db")  # your DB name
cursor = conn.cursor()

cursor.execute("DELETE FROM patient")
cursor.execute("DELETE FROM consultation")
cursor.execute("DELETE FROM prescription")
cursor.execute("DELETE FROM labs")
cursor.execute("DELETE FROM radiology")

conn.commit()
conn.close()