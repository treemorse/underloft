import os
import dotenv
from sqlalchemy import create_engine, text

dotenv.load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Disable transaction
    conn.execution_options(isolation_level="AUTOCOMMIT") 
    
    # Convert columns to VARCHAR while preserving data
    migration_queries = [
        "ALTER TABLE users ALTER COLUMN user_id TYPE VARCHAR USING user_id::VARCHAR",
        "ALTER TABLE registrations ALTER COLUMN user_id TYPE VARCHAR USING user_id::VARCHAR",
        "ALTER TABLE attendance ALTER COLUMN user_id TYPE VARCHAR USING user_id::VARCHAR"
    ]
    
    for query in migration_queries:
        try:
            conn.execute(text(query))
            print(f"Success: {query}")
        except Exception as e:
            print(f"Error executing {query}: {str(e)}")