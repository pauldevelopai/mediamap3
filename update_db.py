from app import app, db
from models import User, Chat, Message, Lesson, UserLesson, OrganizationInfo, OrganizationFact, Translation
from sqlalchemy import inspect

print("Current database location:", app.config['SQLALCHEMY_DATABASE_URI'])

with app.app_context():
    # Add new columns to User table
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('user')]
    
    if 'latitude' not in columns:
        with db.engine.connect() as conn:
            conn.execute(db.text('ALTER TABLE user ADD COLUMN latitude FLOAT'))
            conn.execute(db.text('ALTER TABLE user ADD COLUMN longitude FLOAT'))
            conn.execute(db.text('ALTER TABLE user ADD COLUMN location_name VARCHAR(200)'))
            conn.commit()
    
    # This will add new tables while preserving existing ones
    db.create_all()
    print("Database updated with organization facts table!")
    
    # Verify the tables were created
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    print("\nExisting tables:", existing_tables)

    print("Database updated with translation table!")
    
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    print("\nExisting tables:", existing_tables) 