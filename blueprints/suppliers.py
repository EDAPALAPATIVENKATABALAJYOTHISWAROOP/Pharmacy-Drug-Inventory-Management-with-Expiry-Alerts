from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, Response
from blueprints.auth import login_required
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import io

suppliers_bp = Blueprint('suppliers', __name__, url_prefix='/suppliers')

@suppliers_bp.route('/')
@login_required('Admin')
def list_suppliers():
    from app import get_db
    cur = get_db().cursor()
    cur.execute("SELECT * FROM suppliers ORDER BY supplier_name")
    suppliers = cur.fetchall()
    return render_template('suppliers/list.html', suppliers=suppliers)

@suppliers_bp.route('/add', methods=['POST'])
@login_required('Admin')
def add_supplier():
    from app import get_db
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO suppliers (supplier_name, contact_person, phone, email, gst_number, address)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (request.form['supplier_name'], request.form['contact_person'], request.form['phone'], 
              request.form['email'], request.form['gst_number'], request.form['address']))
        db.commit()
        flash('Supplier added successfully.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error adding supplier: {str(e)}', 'danger')
        
    return redirect(url_for('suppliers.list_suppliers'))

@suppliers_bp.route('/pos', methods=['GET'])
@login_required('Admin')
def pos():
    from app import get_db
    cur = get_db().cursor()
    
    cur.execute("""
        SELECT p.*, s.supplier_name, u.full_name as creator_name
        FROM purchase_orders p
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN users u ON p.created_by = u.user_id
        ORDER BY p.order_date DESC
    """)
    po_list = cur.fetchall()
    
    cur.execute("SELECT * FROM suppliers ORDER BY supplier_name")
    suppliers = cur.fetchall()
    
    cur.execute("SELECT d.drug_id, d.drug_name, category FROM drugs d ORDER BY d.drug_name")
    drugs = cur.fetchall()
    
    return render_template('suppliers/pos.html', po_list=po_list, suppliers=suppliers, drugs=drugs)

@suppliers_bp.route('/pos/create', methods=['POST'])
@login_required('Admin')
def create_po():
    from app import get_db
    supplier_id = request.form['supplier_id']
    expected_date = request.form['expected_date']
    
    drug_ids = request.form.getlist('drug_id[]')
    quantities = request.form.getlist('quantity[]')
    prices = request.form.getlist('price[]')
    
    if not drug_ids:
        flash('Cannot create empty PO.', 'danger')
        return redirect(url_for('suppliers.pos'))
        
    db = get_db()
    cur = db.cursor()
    
    try:
        total_val = 0
        for i in range(len(drug_ids)):
            total_val += (int(quantities[i]) * float(prices[i]))
            
        cur.execute("""
            INSERT INTO purchase_orders (supplier_id, created_by, order_date, expected_date, status, total_value)
            VALUES (?, ?, date('now'), ?, 'Pending', ?)
        """, (supplier_id, session['user_id'], expected_date, total_val))
        po_id = cur.lastrowid
        
        cur.execute("""
            INSERT INTO activity_log (user_id, action, table_name, record_id)
            VALUES (?, ?, ?, ?)
        """, (session['user_id'], f'Raised PO #{po_id} for Supplier ID {supplier_id}', 'purchase_orders', po_id))
        
        for i in range(len(drug_ids)):
            cur.execute("""
                INSERT INTO po_items (po_id, drug_id, quantity, price)
                VALUES (?, ?, ?, ?)
            """, (po_id, drug_ids[i], quantities[i], prices[i]))
            
        db.commit()
        flash(f'Purchase Order #{po_id} generated successfully.', 'success')
        return redirect(url_for('suppliers.pos'))
        
    except Exception as e:
        db.rollback()
        flash(f'Error creating PO: {str(e)}', 'danger')
        return redirect(url_for('suppliers.pos'))

@suppliers_bp.route('/pos/<int:po_id>/deliver', methods=['POST'])
@login_required('Admin')
def mark_po_delivered(po_id):
    from app import get_db
    db = get_db()
    cur = db.cursor()
    
    try:
        cur.execute("SELECT status, supplier_id FROM purchase_orders WHERE po_id = ?", (po_id,))
        po = cur.fetchone()
        
        if not po or po['status'] != 'Pending':
            flash('Invalid or already processed PO.', 'danger')
            return redirect(url_for('suppliers.pos'))
            
        cur.execute("SELECT * FROM po_items WHERE po_id = ?", (po_id,))
        items = cur.fetchall()
        
        today = datetime.date.today()
        exp = today.replace(year=today.year + 2).isoformat()
        
        for item in items:
            batch_no = f"PO{po_id}D{item['drug_id']}"
            mrp = float(item['price']) * 1.5 
            
            cur.execute("""
                INSERT INTO drug_batches (drug_id, supplier_id, batch_number, mfg_date, expiry_date, purchase_price, mrp, quantity, min_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10)
            """, (item['drug_id'], po['supplier_id'], batch_no, today.isoformat(), exp, item['price'], mrp, item['quantity']))
            
        cur.execute("UPDATE purchase_orders SET status = 'Delivered' WHERE po_id = ?", (po_id,))
        
        cur.execute("""
            INSERT INTO activity_log (user_id, action, table_name, record_id)
            VALUES (?, ?, ?, ?)
        """, (session['user_id'], f'Marked PO #{po_id} as Delivered. Stock updated.', 'purchase_orders', po_id))
        
        db.commit()
        flash(f'PO #{po_id} marked as Delivered. Stock batches auto-generated.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error updating PO: {str(e)}', 'danger')
        
    return redirect(url_for('suppliers.pos'))

@suppliers_bp.route('/pos/<int:po_id>/pdf')
@login_required('Admin')
def po_pdf(po_id):
    from app import get_db
    cur = get_db().cursor()
    
    cur.execute("""
        SELECT p.*, s.*
        FROM purchase_orders p
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE p.po_id = ?
    """, (po_id,))
    po = cur.fetchone()
    
    try:
        cur.execute("""
            SELECT i.*, d.drug_name 
            FROM po_items i
            JOIN drugs d ON i.drug_id = d.drug_id
            WHERE i.po_id = ?
        """, (po_id,))
        items = cur.fetchall()
    except:
        items = []
        
    if not po:
        flash('PO not found.', 'danger')
        return redirect(url_for('suppliers.pos'))
        
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph("<b>PHARMASYS MEDICAL STORE</b>", styles['Title']))
    elements.append(Paragraph("<b>PURCHASE ORDER</b>", styles['Heading2']))
    elements.append(Spacer(1, 10))
    
    elements.append(Paragraph(f"<b>PO Number:</b> #{po['po_id']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Order Date:</b> {po['order_date']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Expected Date:</b> {po['expected_date']}", styles['Normal']))
    elements.append(Spacer(1, 10))
    
    elements.append(Paragraph(f"<b>To Supplier:</b> {po['supplier_name']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Email:</b> {po['email']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Phone:</b> {po['phone']}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    data = [['S.No', 'Medicine Name', 'Req. Qty', 'Unit Price (₹)', 'Total (₹)']]
    for idx, item in enumerate(items):
        data.append([idx + 1, item['drug_name'], item['quantity'], f"{float(item['price']):.2f}", f"{float(item['price']) * item['quantity']:.2f}"])
        
    t = Table(data, colWidths=[40, 250, 80, 80, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>Grand Total:</b> ₹ {float(po['total_value']):.2f}", styles['Heading3']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response = Response(pdf, mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=PO_{po_id}.pdf'
    return response
