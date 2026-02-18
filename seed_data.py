"""
Seed data script for testing and development
Creates sample families, children, and QR codes for testing the complete flow
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
import random

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import Database, init_database, AsyncSessionLocal
from sqlalchemy import text

# Sample data
SAMPLE_FAMILIES = [
    {"family_name": "Johnson Family"},
    {"family_name": "Smith Family"},
    {"family_name": "Williams Family"},
    {"family_name": "Brown Family"},
    {"family_name": "Davis Family"}
]

SAMPLE_PARENTS = [
    {"first_name": "Michael", "last_name": "Johnson", "phone": "555-0101", "email": "michael.j@email.com", "relationship": "father"},
    {"first_name": "Sarah", "last_name": "Johnson", "phone": "555-0102", "email": "sarah.j@email.com", "relationship": "mother"},
    {"first_name": "David", "last_name": "Smith", "phone": "555-0201", "email": "david.s@email.com", "relationship": "father"},
    {"first_name": "Emily", "last_name": "Smith", "phone": "555-0202", "email": "emily.s@email.com", "relationship": "mother"},
    {"first_name": "James", "last_name": "Williams", "phone": "555-0301", "email": "james.w@email.com", "relationship": "guardian"},
    {"first_name": "Jennifer", "last_name": "Brown", "phone": "555-0401", "email": "jennifer.b@email.com", "relationship": "mother"},
    {"first_name": "Robert", "last_name": "Davis", "phone": "555-0501", "email": "robert.d@email.com", "relationship": "father"}
]

SAMPLE_CHILDREN = [
    {"first_name": "Emma", "last_name": "Johnson", "birth_date": "2021-03-15", "allergies": "Peanuts", "medications": None, "special_notes": "Shy, needs gentle encouragement"},
    {"first_name": "Noah", "last_name": "Johnson", "birth_date": "2019-07-22", "allergies": None, "medications": None, "special_notes": "Very active, loves outdoor play"},
    {"first_name": "Olivia", "last_name": "Smith", "birth_date": "2020-11-08", "allergies": "None", "medications": "None", "special_notes": "Likes to draw and color"},
    {"first_name": "Liam", "last_name": "Williams", "birth_date": "2018-05-30", "allergies": "Dairy", "medications": "None", "special_notes": "Needs reminder to use inhaler before running"},
    {"first_name": "Sophia", "last_name": "Brown", "birth_date": "2022-01-12", "allergies": "None", "medications": "None", "special_notes": "New to the program, may need extra attention"},
    {"first_name": "Mason", "last_name": "Davis", "birth_date": "2019-09-03", "allergies": "None", "medications": "None", "special_notes": "Loves building blocks and puzzles"},
    {"first_name": "Ava", "last_name": "Johnson", "birth_date": "2020-06-18", "allergies": "None", "medications": "None", "special_notes": "Very social, makes friends easily"},
    {"first_name": "Lucas", "last_name": "Smith", "birth_date": "2021-12-25", "allergies": "None", "medications": "None", "special_notes": "Enjoys music and singing"}
]

def generate_qr_value(child_first_name, child_last_name, index):
    """Generate a unique QR code value"""
    return f"KID-{child_first_name.upper()}-{child_last_name.upper()}-{index:03d}"

async def create_sample_data():
    """Create sample data for testing"""
    print("Creating sample data...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Create families
            family_ids = []
            for family_data in SAMPLE_FAMILIES:
                await db.execute(
                    text("INSERT INTO families (family_name) VALUES (:family_name)"),
                    family_data
                )
                family_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
                family_ids.append(family_id)
                print(f"Created family: {family_data['family_name']}")
            
            # Create parents
            parent_ids = []
            for i, parent_data in enumerate(SAMPLE_PARENTS):
                family_id = family_ids[i // 2]  # 2 parents per family
                await db.execute(
                    text("""
                        INSERT INTO parents (family_id, first_name, last_name, phone, email, relationship)
                        VALUES (:family_id, :first_name, :last_name, :phone, :email, :relationship)
                    """),
                    {**parent_data, "family_id": family_id}
                )
                parent_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
                parent_ids.append(parent_id)
                print(f"Created parent: {parent_data['first_name']} {parent_data['last_name']}")
            
            # Create children and QR codes
            child_ids = []
            for i, child_data in enumerate(SAMPLE_CHILDREN):
                family_id = family_ids[i // 2]  # 2 children per family
                qr_value = generate_qr_value(child_data["first_name"], child_data["last_name"], i + 1)
                
                # Create child
                await db.execute(
                    text("""
                        INSERT INTO children (family_id, first_name, last_name, birth_date, allergies, medications, special_notes)
                        VALUES (:family_id, :first_name, :last_name, :birth_date, :allergies, :medications, :special_notes)
                    """),
                    {**child_data, "family_id": family_id}
                )
                child_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
                child_ids.append(child_id)
                
                # Create QR code
                await db.execute(
                    text("INSERT INTO qr_codes (child_id, qr_value) VALUES (:child_id, :qr_value)"),
                    {"child_id": child_id, "qr_value": qr_value}
                )
                
                print(f"Created child: {child_data['first_name']} {child_data['last_name']} with QR: {qr_value}")
            
            # Create some sample attendance records
            programs = await db.execute(text("SELECT id, name FROM programs ORDER BY id"))
            program_list = programs.fetchall()
            
            # Create attendance for the last few weeks
            for week_offset in range(4):
                checkin_date = datetime.now() - timedelta(weeks=week_offset, days=0)
                
                # Randomly check in some children
                for child_id in random.sample(child_ids, min(5, len(child_ids))):
                    program = random.choice(program_list)
                    
                    await db.execute(
                        text("""
                            INSERT INTO attendance (child_id, program_id, station_id, checkin_time, created_by)
                            VALUES (:child_id, :program_id, :station_id, :checkin_time, :created_by)
                        """),
                        {
                            "child_id": child_id,
                            "program_id": program[0],
                            "station_id": random.choice(["entrance-a", "entrance-b"]),
                            "checkin_time": checkin_date.replace(hour=9, minute=30 + random.randint(0, 30)),
                            "created_by": random.choice(["Alice", "Bob", "Carol", "Dave"])
                        }
                    )
            
            await db.commit()
            print("Sample data created successfully!")
            
            # Print summary
            print("\n=== Sample Data Summary ===")
            print(f"Families: {len(family_ids)}")
            print(f"Parents: {len(parent_ids)}")
            print(f"Children: {len(child_ids)}")
            print(f"QR Codes: {len(child_ids)}")
            
            print("\n=== Test QR Codes ===")
            for i, child_data in enumerate(SAMPLE_CHILDREN):
                qr_value = generate_qr_value(child_data["first_name"], child_data["last_name"], i + 1)
                print(f"{qr_value} - {child_data['first_name']} {child_data['last_name']}")
            
            print("\n=== Test Instructions ===")
            print("1. Start the application: docker-compose up --build")
            print("2. Navigate to: http://localhost:8000")
            print("3. Use any of the QR codes above to test scanning")
            print("4. Test registration with: http://localhost:8000/register")
            
        except Exception as e:
            print(f"Error creating sample data: {e}")
            await db.rollback()

async def clear_sample_data():
    """Clear all sample data"""
    print("Clearing sample data...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Delete in order of dependencies
            await db.execute(text("DELETE FROM attendance"))
            await db.execute(text("DELETE FROM qr_codes"))
            await db.execute(text("DELETE FROM children"))
            await db.execute(text("DELETE FROM parents"))
            await db.execute(text("DELETE FROM families"))
            await db.commit()
            print("Sample data cleared!")
            
        except Exception as e:
            print(f"Error clearing sample data: {e}")
            await db.rollback()

async def main():
    """Main function"""
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        await clear_sample_data()
    else:
        await init_database()
        await create_sample_data()

if __name__ == "__main__":
    asyncio.run(main())
