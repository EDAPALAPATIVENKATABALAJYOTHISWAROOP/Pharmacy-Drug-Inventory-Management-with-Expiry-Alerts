from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, session
from blueprints.auth import login_required
import datetime
import csv
import io

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

@inventory_bp.route('/')
@login_required()
def list_drugs():
    from app import get_db
    db = get_db()
    cur = db.cursor()
    
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '').strip()
    company_filter = request.args.get('company', '').strip()
    per_page = 20
    offset = (page - 1) * per_page
    
    base_query = "FROM drug_batches b JOIN drugs d ON b.drug_id = d.drug_id LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id WHERE 1=1"
    params = []
    
    if search_query:
        base_query += " AND (d.drug_name LIKE ? OR d.generic_name LIKE ? OR b.batch_number LIKE ?)"
        lk = f"%{search_query}%"
        params.extend([lk, lk, lk])
        
    if category_filter:
        base_query += " AND d.category = ?"
        params.append(category_filter)
        
    if company_filter:
        base_query += " AND d.company = ?"
        params.append(company_filter)
        
    count_query = f"SELECT COUNT(DISTINCT d.drug_id) as count {base_query}"
    cur.execute(count_query, params)
    total_records = cur.fetchone()['count']
    total_pages = (total_records + per_page - 1) // per_page
    if total_pages == 0:
        total_pages = 1
    
    data_query = f"""
        SELECT d.drug_id, d.drug_name, d.category, d.company, d.gst_percent,
               GROUP_CONCAT(b.batch_number, ', ') as batch_number,
               MIN(b.expiry_date) as expiry_date,
               MAX(b.mrp) as mrp, 
               SUM(b.quantity) as quantity, 
               MAX(b.min_threshold) as min_threshold,
               GROUP_CONCAT(DISTINCT s.supplier_name) as supplier_name
        {base_query}
        GROUP BY d.drug_id, d.drug_name, d.category, d.company, d.gst_percent
        ORDER BY d.drug_name ASC
        LIMIT ? OFFSET ?
    """
    cur.execute(data_query, params + [per_page, offset])
    inventory = cur.fetchall()
    
    cur.execute("SELECT DISTINCT category FROM drugs ORDER BY category")
    categories = [row['category'] for row in cur.fetchall()]
    
    cur.execute("SELECT DISTINCT company FROM drugs WHERE company IS NOT NULL AND company != '' ORDER BY company")
    companies = [row['company'] for row in cur.fetchall()]
    
    cur.execute("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    suppliers = cur.fetchall()
    
    today = datetime.date.today()
    
    # In SQLite string iso dates can be compared like strings, so we pass python dates as strings for Jinja
    delta_30 = (today + datetime.timedelta(days=30)).isoformat()
    delta_90 = (today + datetime.timedelta(days=90)).isoformat()
    today_str = today.isoformat()
    
    # Needs to convert rows to standard dict so template can use date objects or strings
    invent_list = []
    for row in inventory:
        dict_row = dict(row)
        if dict_row['expiry_date']:
            dict_row['expiry_date_obj'] = datetime.datetime.strptime(dict_row['expiry_date'], '%Y-%m-%d').date()
        else:
            dict_row['expiry_date_obj'] = today
        invent_list.append(dict_row)
    
    return render_template('inventory/list.html', 
                           inventory=invent_list, 
                           categories=categories, 
                           companies=companies,
                           suppliers=suppliers,
                           page=page, 
                           total_pages=total_pages,
                           today=today_str,
                           delta_30=delta_30,
                           delta_90=delta_90)

@inventory_bp.route('/add', methods=['POST'])
@login_required('Pharmacist')
def add_drug():
    if request.method == 'POST':
        from app import get_db
        db = get_db()
        cur = db.cursor()
        
        try:
            cur.execute("SELECT drug_id FROM drugs WHERE drug_name = ? AND company = ?", 
                       (request.form['drug_name'], request.form['company']))
            existing_drug = cur.fetchone()
            
            if existing_drug:
                drug_id = existing_drug['drug_id']
            else:
                cur.execute("""
                    INSERT INTO drugs (drug_name, generic_name, category, company, gst_percent, unit)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (request.form['drug_name'], request.form['generic_name'], request.form['category'], 
                      request.form['company'], request.form['gst_percent'], request.form['unit']))
                drug_id = cur.lastrowid
                
            cur.execute("""
                INSERT INTO drug_batches (drug_id, supplier_id, batch_number, mfg_date, expiry_date, purchase_price, mrp, quantity, min_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (drug_id, request.form['supplier_id'], request.form['batch_number'], 
                  request.form['mfg_date'], request.form['expiry_date'], request.form['purchase_price'], 
                  request.form['mrp'], request.form['quantity'], request.form['min_threshold']))
            
            batch_id = cur.lastrowid
            
            cur.execute("""
                INSERT INTO activity_log (user_id, action, table_name, record_id)
                VALUES (?, ?, ?, ?)
            """, (session['user_id'], f"Added stock batch {request.form['batch_number']} for {request.form['drug_name']}", 'drug_batches', batch_id))
            
            db.commit()
            flash(f"Successfully added {request.form['quantity']} units of {request.form['drug_name']}", 'success')
            
        except Exception as e:
            db.rollback()
            flash(f'Error adding drug setup: {str(e)}', 'danger')
            
        return redirect(url_for('inventory.list_drugs'))

@inventory_bp.route('/export')
@login_required()
def export_csv():
    from app import get_db
    cur = get_db().cursor()
    query = """
        SELECT d.drug_name, d.category, d.company, 
               b.batch_number, b.expiry_date, b.mrp, b.quantity, s.supplier_name
        FROM drug_batches b
        JOIN drugs d ON b.drug_id = d.drug_id
        LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id
        ORDER BY d.drug_name ASC
    """
    cur.execute(query)
    records = cur.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Drug Name', 'Category', 'Company', 'Batch Number', 'Expiry Date', 'MRP', 'Current Stock', 'Supplier'])
    for row in records:
        writer.writerow([row['drug_name'], row['category'], row['company'], row['batch_number'], 
                         row['expiry_date'], row['mrp'], row['quantity'], row['supplier_name']])
        
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers["Content-Disposition"] = "attachment; filename=inventory_report.csv"
    return response

@inventory_bp.route('/alerts')
@login_required()
def list_alerts():
    from app import get_db
    cur = get_db().cursor()
    
    query_base = """
        SELECT b.batch_id, d.drug_name, b.batch_number, b.expiry_date, b.quantity, b.min_threshold, s.supplier_name,
               CAST(julianday(b.expiry_date) - julianday('now') AS INTEGER) as days_remaining
        FROM drug_batches b
        JOIN drugs d ON b.drug_id = d.drug_id
        LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id
    """
    
    cur.execute(query_base + " WHERE b.expiry_date < date('now') ORDER BY b.expiry_date ASC")
    expired = [dict(r) for r in cur.fetchall()]
    
    cur.execute(query_base + " WHERE b.expiry_date >= date('now') AND b.expiry_date <= date('now', '+30 days') ORDER BY b.expiry_date ASC")
    critical = [dict(r) for r in cur.fetchall()]
    
    cur.execute(query_base + " WHERE b.expiry_date > date('now', '+30 days') AND b.expiry_date <= date('now', '+90 days') ORDER BY b.expiry_date ASC")
    warning = [dict(r) for r in cur.fetchall()]
    
    cur.execute(query_base + " WHERE b.quantity <= b.min_threshold AND b.quantity > 0 ORDER BY b.quantity ASC")
    low_stock = [dict(r) for r in cur.fetchall()]
    
    # Convert dates for jinja format
    for lst in [expired, critical, warning, low_stock]:
        for row in lst:
            if row['expiry_date']:
                row['expiry_date_obj'] = datetime.datetime.strptime(row['expiry_date'], '%Y-%m-%d').date()
    
    return render_template('alerts/list.html', expired=expired, critical=critical, warning=warning, low_stock=low_stock)


@inventory_bp.route('/delete-batch/<int:batch_id>', methods=['POST'])
@login_required('Pharmacist')
def delete_expired_batch(batch_id):
    from app import get_db
    db = get_db()
    cur = db.cursor()
    try:
        # Fetch batch info for the activity log
        cur.execute("""
            SELECT b.batch_number, d.drug_name
            FROM drug_batches b
            JOIN drugs d ON b.drug_id = d.drug_id
            WHERE b.batch_id = ? AND b.expiry_date < date('now')
        """, (batch_id,))
        row = cur.fetchone()
        if not row:
            flash('Batch not found or not expired.', 'warning')
            return redirect(url_for('inventory.list_alerts'))

        cur.execute("DELETE FROM drug_batches WHERE batch_id = ?", (batch_id,))
        cur.execute("""
            INSERT INTO activity_log (user_id, action, table_name, record_id)
            VALUES (?, ?, ?, ?)
        """, (session['user_id'],
               f"Deleted expired batch {row['batch_number']} of {row['drug_name']}",
               'drug_batches', batch_id))
        db.commit()
        flash(f"Deleted expired batch '{row['batch_number']}' of {row['drug_name']}.", 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error deleting batch: {str(e)}', 'danger')
    return redirect(url_for('inventory.list_alerts'))
