import random
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

def seed_db(app):
    from app import get_db
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        
        # Check if already seeded with batches
        cur.execute("SELECT COUNT(*) as count FROM drug_batches")
        if cur.fetchone()['count'] > 0:
            return
            
        print("Seeding database with 100 dummy drug batches...")
                    
        # 1. Add Suppliers
        suppliers = ['PharmaCorp', 'MediSupply', 'HealthPlus', 'Global Meds', 'CureAll Pharma']
        supplier_ids = []
        for s in suppliers:
            cur.execute("INSERT INTO suppliers (supplier_name, contact_person, phone) VALUES (?, ?, ?)",
                        (s, 'Contact ' + s, '1234567890'))
            supplier_ids.append(cur.lastrowid)
            
        # 2. Add Drugs
        drug_prefixes = ['Amoxi', 'Para', 'Cetro', 'Metro', 'Azithro', 'Cipro', 'Leva', 'Dolo', 'Rabe', 'Panto']
        drug_suffixes = ['cillin', 'cetamol', 'zine', 'nidazole', 'mycin', 'floxacin', 'set', 'prazole']
        categories = ['Tablet', 'Syrup', 'Injection', 'Capsule', 'Ointment', 'Drops']
        companies = ['Sun Pharma', 'Cipla', 'Dr Reddys', 'Lupin', 'Aurobindo']
        
        drug_ids = []
        for i in range(100): # 100 unique drug bases
            name = random.choice(drug_prefixes) + random.choice(drug_suffixes) + " " + str(random.choice([100, 250, 500, 650])) + "mg"
            category = random.choice(categories)
            company = random.choice(companies)
            
            cur.execute("""INSERT INTO drugs (drug_name, generic_name, category, company, gst_percent, unit) 
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (name, name.split()[0], category, company, 12.0, 'Strip' if category in ['Tablet', 'Capsule'] else 'Bottle'))
            drug_ids.append(cur.lastrowid)
            
        # 3. Add Batches (200 items)
        for i in range(200):
            drug_id = random.choice(drug_ids)
            supplier_id = random.choice(supplier_ids)
            batch_num = f"BTH-{random.randint(1000, 9999)}"
            mfg_date = datetime.now() - timedelta(days=random.randint(10, 300))
            
            # Mix of Good, Warning (<=90), Critical (<=30), and Expired
            days_to_expiry = random.randint(-40, 400)
            expiry_date = datetime.now() + timedelta(days=days_to_expiry)
            
            purchase_price = round(random.uniform(10.0, 500.0), 2)
            mrp = round(purchase_price * random.uniform(1.2, 2.0), 2)
            
            # Mix of normal and low stock
            quantity = random.randint(0, 200)
            min_threshold = random.randint(10, 50)
            
            cur.execute("""INSERT INTO drug_batches 
                           (drug_id, supplier_id, batch_number, mfg_date, expiry_date, purchase_price, mrp, quantity, min_threshold)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (drug_id, supplier_id, batch_num, mfg_date.strftime('%Y-%m-%d'), 
                         expiry_date.strftime('%Y-%m-%d'), purchase_price, mrp, quantity, min_threshold))
                         
        db.commit()
        print("Database seeded successfully with 200 batches!")
