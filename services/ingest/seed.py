import os, psycopg
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL")

DOC = {
    "celex": "32006R1907",
    "title": "REACH (dummy)",
    "eli_uri": "/eli/reg/2006/1907/oj",
    "doc_type": "regulation",
    "lang": "en",
    "date": date(2006,12,30),
    "hash": "dummyhash"
}
SPAN = {
    "ref_label": "REACH Art.57(1)",
    "article": "57",
    "annex": None,
    "paragraph": "1",
    "text": "Substances meeting the criteria in Article 57(1) (dummy excerpt for smoke test).",
    "start_char": 0,
    "end_char": 80
}

def main():
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("BEGIN;")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO documents (celex,title,eli_uri,doc_type,lang,date,hash)
               VALUES (%(celex)s,%(title)s,%(eli_uri)s,%(doc_type)s,%(lang)s,%(date)s,%(hash)s)
               RETURNING doc_id;""", DOC
        )
        doc_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO spans (doc_id,ref_label,article,annex,paragraph,text,start_char,end_char)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s);""",
            (doc_id, SPAN["ref_label"], SPAN["article"], SPAN["annex"], SPAN["paragraph"],
             SPAN["text"], SPAN["start_char"], SPAN["end_char"])
        )
        conn.commit()
        print(f"Seeded doc_id={doc_id} with one span.")
    print("Done.")

if __name__ == "__main__":
    main()