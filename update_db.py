from app import app, db
from models import Lesson, UserLesson, OrganizationInfo
from sqlalchemy import inspect

print("Current database location:", app.config['SQLALCHEMY_DATABASE_URI'])

with app.app_context():
    # This will add new tables while preserving existing ones
    db.create_all()
    print("Database updated with lesson tables!")
    
    # Verify the tables were created
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    print("\nExisting tables:", existing_tables) 