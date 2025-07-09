import os
from urllib.parse import urlsplit, unquote
from dotenv import load_dotenv
import psycopg2

load_dotenv()

database_url = os.getenv('DATABASE_URL')

parsed_url = urlsplit(database_url)

db_username = unquote(parsed_url.username)
db_password = unquote(parsed_url.password) if parsed_url.password else None
db_host = parsed_url.hostname
db_port = parsed_url.port if parsed_url.port else 5432
db_name = unquote(parsed_url.path[1:])

conn = psycopg2.connect(
    dbname=db_name,
    user=db_username,
    password=db_password,
    host=db_host,
    port=db_port
)

output_filename = 'data/users.csv'

try:
    with conn.cursor() as cursor, open(output_filename, 'w') as csv_file:
        cursor.copy_expert(
            "COPY (SELECT * FROM users) TO STDOUT WITH CSV HEADER",
            csv_file
        )
    print(f"Successfully exported to {output_filename}")
except Exception as e:
    print(f"Error: {e}")
finally:
    if conn:
        conn.close()