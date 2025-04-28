import os
from urllib.parse import urlsplit, unquote
from dotenv import load_dotenv
import psycopg2

# Load environment variables from .env file
load_dotenv()

# Get database URL from environment variables
database_url = os.getenv('DATABASE_URL')

# Parse the database URL
parsed_url = urlsplit(database_url)

# Extract connection components
db_username = unquote(parsed_url.username)
db_password = unquote(parsed_url.password) if parsed_url.password else None
db_host = parsed_url.hostname
db_port = parsed_url.port if parsed_url.port else 5432
db_name = unquote(parsed_url.path[1:])  # Remove leading slash from path

# Establish database connection
conn = psycopg2.connect(
    dbname=db_name,
    user=db_username,
    password=db_password,
    host=db_host,
    port=db_port
)

# Create output file
output_filename = 'data/users.csv'

try:
    with conn.cursor() as cursor, open(output_filename, 'w') as csv_file:
        # Use COPY command to stream data directly to CSV
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