# check_contents.py
from database import engine

with engine.connect() as conn:
    # Fetch all rows from people
    people_rows = conn.exec_driver_sql("SELECT * FROM people").fetchall()
    articles_rows = conn.exec_driver_sql("SELECT * FROM articles").fetchall()
    person_article_rows = conn.exec_driver_sql("SELECT * FROM person_articles").fetchall()

    print("\n📍 People Table:")
    for row in people_rows:
        print(dict(row._mapping))  # row._mapping turns Row into a dict

    # print("\n📍 Articles Table:")
    # for row in articles_rows:
    #     print(dict(row._mapping))

    # print("\n📍 People-Articles Table:")
    # for row in person_article_rows:
    #     print(dict(row._mapping))
