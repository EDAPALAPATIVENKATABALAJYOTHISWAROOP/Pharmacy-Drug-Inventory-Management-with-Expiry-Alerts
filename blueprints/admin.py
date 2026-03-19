from flask import Blueprint, render_template, session
from blueprints.auth import login_required
import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@login_required('Admin')
def dashboard():
    from app import get_db
    db = get_db()
    cur = db.cursor()
    
    # 1. KPIs
    cur.execute("SELECT COUNT(DISTINCT drug_id) as total FROM drug_batches WHERE quantity > 0")
    total_drugs = cur.fetchone()['total']
    
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) as msales FROM bills WHERE date(bill_date) = date('now')")
    today_sales = float(cur.fetchone()['msales'])
    
    cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE expiry_date <= date('now', '+30 days')")
    expiry_alerts = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE quantity <= min_threshold AND quantity > 0")
    low_stock = cur.fetchone()['count']
    
    # 2. Last 7 Days Sales Chart Data
    cur.execute("""
        SELECT date(bill_date) as bdate, COALESCE(SUM(total_amount), 0) as total
        FROM bills 
        WHERE bill_date >= date('now', '-6 days')
        GROUP BY date(bill_date)
        ORDER BY bdate ASC
    """)
    sales_data = cur.fetchall()
    
    today = datetime.date.today()
    dates = []
    sales = []
    
    # Fill missing dates
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        dates.append(d.strftime('%a, %d %b'))
        
        found = False
        for row in sales_data:
            if row['bdate'] == d.isoformat():
                sales.append(float(row['total']))
                found = True
                break
        if not found:
            sales.append(0.0)
            
    # 3. Top 10 Best Selling Drugs (This Month)
    cur.execute("""
        SELECT d.drug_name, SUM(i.quantity) as total_sold
        FROM bill_items i
        JOIN drug_batches b ON i.batch_id = b.batch_id
        JOIN drugs d ON d.drug_id = b.drug_id
        JOIN bills bi ON i.bill_id = bi.bill_id
        WHERE strftime('%Y-%m', bi.bill_date) = strftime('%Y-%m', 'now')
        GROUP BY d.drug_id, d.drug_name
        ORDER BY total_sold DESC
        LIMIT 10
    """)
    top_drugs = cur.fetchall()
    top_labels = [row['drug_name'] for row in top_drugs]
    top_data = [int(row['total_sold']) for row in top_drugs]
    
    # 4. Category Breakdown
    cur.execute("""
        SELECT d.category, COUNT(b.batch_id) as total_batches
        FROM drug_batches b
        JOIN drugs d ON d.drug_id = b.drug_id
        WHERE b.quantity > 0
        GROUP BY d.category
    """)
    cat_data = cur.fetchall()
    cat_labels = [row['category'] for row in cat_data]
    cat_values = [int(row['total_batches']) for row in cat_data]
    
    return render_template('admin/dashboard.html', 
                           total_drugs=total_drugs, today_sales=today_sales,
                           expiry_alerts=expiry_alerts, low_stock=low_stock,
                           dates=dates, sales=sales,
                           top_labels=top_labels, top_data=top_data,
                           cat_labels=cat_labels, cat_values=cat_values)

@admin_bp.route('/logs')
@login_required('Admin')
def logs():
    from app import get_db
    cur = get_db().cursor()
    cur.execute("""
        SELECT l.*, u.full_name, u.role
        FROM activity_log l
        JOIN users u ON l.user_id = u.user_id
        ORDER BY l.timestamp DESC
        LIMIT 100
    """)
    
    logs_data = []
    for row in cur.fetchall():
        d = dict(row)
        try:
            d['timestamp_obj'] = datetime.datetime.strptime(d['timestamp'], '%Y-%m-%d %H:%M:%S')
        except:
            d['timestamp_obj'] = datetime.datetime.now()
        logs_data.append(d)
        
    return render_template('admin/logs.html', logs=logs_data)
