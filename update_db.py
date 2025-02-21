from app import app, db
from models import User, Chat, Message, Lesson, UserLesson, OrganizationInfo, OrganizationFact, Translation, TranslationFeedback
from sqlalchemy import inspect, text

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
    
    # Check if rating column exists
    has_rating = False
    for column in inspector.get_columns('translation'):
        if column['name'] == 'rating':
            has_rating = True
            break
    
    # Add rating column if it doesn't exist
    if not has_rating:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE translation ADD COLUMN rating INTEGER'))
            conn.commit()
            print("Added rating column to translation table!")
    
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

    print("Database updated with translation rating column!")

    print("Database updated with translation feedback table!") 