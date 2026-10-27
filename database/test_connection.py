from database.db_connection import get_db_engine
from database.db_models import init_db
from sqlalchemy import text

if __name__ == "__main__":
    print("Testing connection to Neon PostgreSQL...")

    # 1. Test table creation
    success = init_db()
    if success:
        print("✅ Tables initialized successfully!")

        # 2. Run a lightweight query to check response time/connection
        engine = get_db_engine()
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            db_version = result.fetchone()[0]
            print(f"✅ Connected successfully! PostgreSQL Version: {db_version}")
    else:
        print("❌ Connection or table creation failed. Check your DATABASE_URL in .env.")