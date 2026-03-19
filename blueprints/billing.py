from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, Response
from blueprints.auth import login_required
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import io

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

@billing_bp.route('/', methods=['GET', 'POST'])
@login_required('Pharmacist')
def create_bill():
    if request.method == 'POST':
        from app import get_db
        db = get_db()
        cur = db.cursor()
        
        customer_name = request.form.get('customer_name', 'Walk-in Customer')
        customer_phone = request.form.get('customer_phone', '')
        payment_mode = request.form.get('payment_mode', 'Cash')
        
        batch_ids = request.form.getlist('batch_id[]')
        quantities = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')
        gst_percents = request.form.getlist('gst_percent[]')
        
        if not batch_ids:
            flash('Please add at least one item to the bill.', 'danger')
            return redirect(url_for('billing.create_bill'))
            
        try:
            subtotal = 0
            total_gst = 0
            grand_total = 0
            bill_items_data = []
            
            for i in range(len(batch_ids)):
                b_id = int(batch_ids[i])
                qty = int(quantities[i])
                price = float(unit_prices[i])
                gst_pct = float(gst_percents[i])
                
                cur.execute("SELECT quantity, batch_number FROM drug_batches WHERE batch_id = ?", (b_id,))
                batch_data = cur.fetchone()
                
                if not batch_data or batch_data['quantity'] < qty:
                    raise Exception(f"Insufficient stock for batch {batch_data['batch_number'] if batch_data else b_id}")
                    
                item_total = price * qty
                item_gst = item_total * (gst_pct / 100)
                
                subtotal += item_total
                total_gst += item_gst
                bill_items_data.append((b_id, qty, price, gst_pct, item_total + item_gst))
                
            grand_total = subtotal + total_gst
            
            cur.execute("""
                INSERT INTO bills (customer_name, customer_phone, user_id, subtotal, gst_amount, total_amount, payment_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (customer_name, customer_phone, session['user_id'], subtotal, total_gst, grand_total, payment_mode))
            
            bill_id = cur.lastrowid
            
            for item in bill_items_data:
                b_id, qty, price, gst_pct, item_total = item
                cur.execute("""
                    INSERT INTO bill_items (bill_id, batch_id, quantity, unit_price, gst_percent, total_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (bill_id, b_id, qty, price, gst_pct, item_total))
                cur.execute("UPDATE drug_batches SET quantity = quantity - ? WHERE batch_id = ?", (qty, b_id))
            
            cur.execute("""
                INSERT INTO activity_log (user_id, action, table_name, record_id)
                VALUES (?, ?, ?, ?)
            """, (session['user_id'], f'Created Bill #{bill_id} for ₹{grand_total}', 'bills', bill_id))
            
            db.commit()
            flash('Bill generated successfully!', 'success')
            return redirect(url_for('billing.invoice', bill_id=bill_id))
            
        except Exception as e:
            db.rollback()
            flash(f'Error generating bill: {str(e)}', 'danger')
            return redirect(url_for('billing.create_bill'))
            
    return render_template('billing/create.html')

@billing_bp.route('/history')
@login_required()
def history():
    from app import get_db
    cur = get_db().cursor()
    cur.execute("""
        SELECT b.bill_id, b.customer_name, b.bill_date, b.total_amount, b.payment_mode, u.full_name
        FROM bills b
        JOIN users u ON b.user_id = u.user_id
        ORDER BY b.bill_date DESC LIMIT 50
    """)
    bills = []
    for row in cur.fetchall():
        d = dict(row)
        try:
            d['bill_date_obj'] = datetime.datetime.strptime(d['bill_date'], '%Y-%m-%d %H:%M:%S')
        except:
            d['bill_date_obj'] = datetime.datetime.now()
        bills.append(d)
    return render_template('billing/history.html', bills=bills)

@billing_bp.route('/api/search_drug')
@login_required('Pharmacist')
def search_drug():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
        
    from app import get_db
    cur = get_db().cursor()
    cur.execute("""
        SELECT b.batch_id, d.drug_name, d.category, b.batch_number, 
               b.mrp, b.quantity, d.gst_percent, b.expiry_date
        FROM drug_batches b
        JOIN drugs d ON b.drug_id = d.drug_id
        WHERE (d.drug_name LIKE ? OR d.generic_name LIKE ?)
        AND b.quantity > 0 AND b.expiry_date >= date('now')
        ORDER BY d.drug_name ASC, b.expiry_date ASC
        LIMIT 10
    """, (f'%{query}%', f'%{query}%'))
    
    results = [dict(row) for row in cur.fetchall()]
    return jsonify(results)

@billing_bp.route('/invoice/<int:bill_id>')
@login_required()
def invoice(bill_id):
    from app import get_db
    cur = get_db().cursor()
    
    cur.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,))
    bill = cur.fetchone()
    
    if not bill:
        flash('Bill not found.', 'danger')
        return redirect(url_for('billing.history'))
        
    cur.execute("""
        SELECT i.*, d.drug_name, b.batch_number 
        FROM bill_items i
        JOIN drug_batches b ON i.batch_id = b.batch_id
        JOIN drugs d ON b.drug_id = d.drug_id
        WHERE i.bill_id = ?
    """, (bill_id,))
    items = cur.fetchall()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph("<b>PHARMASYS MEDICAL STORE</b>", styles['Title']))
    elements.append(Paragraph("123 Health Ave, Medical City, India | GSTIN: 29XXXXX0000X1Z5", styles['Normal']))
    elements.append(Paragraph("Phone: +91 9876543210 | Email: contact@pharmasys.com", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph(f"<b>TAX INVOICE</b>", styles['Heading2']))
    elements.append(Paragraph(f"<b>Bill No:</b> {bill['bill_id']} | <b>Date:</b> {bill['bill_date']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Customer:</b> {bill['customer_name']} | <b>Phone:</b> {bill['customer_phone']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Payment Mode:</b> {bill['payment_mode']}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    data = [['S.No', 'Medicine Name', 'Batch', 'Qty', 'Rate\n(₹)', 'GST %', 'CGST\n(₹)', 'SGST\n(₹)', 'Total\n(₹)']]
    for idx, item in enumerate(items):
        qty = item['quantity']
        rate = float(item['unit_price'])
        gst_pct = float(item['gst_percent'])
        base_amt = qty * rate
        gst_amt = base_amt * (gst_pct / 100)
        cgst = sgst = gst_amt / 2
        total = float(item['total_price'])
        
        data.append([idx + 1, item['drug_name'], item['batch_number'], qty, f"{rate:.2f}", f"{gst_pct}%", f"{cgst:.2f}", f"{sgst:.2f}", f"{total:.2f}"])
        
    t = Table(data, colWidths=[30, 160, 60, 40, 50, 40, 50, 50, 55])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 20))
    
    totals_data = [
        ['', '', 'Subtotal:', f"₹ {float(bill['subtotal']):.2f}"],
        ['', '', 'Total GST:', f"₹ {float(bill['gst_amount']):.2f}"],
        ['', '', 'GRAND TOTAL:', f"₹ {float(bill['total_amount']):.2f}"]
    ]
    t2 = Table(totals_data, colWidths=[280, 50, 100, 105])
    t2.setStyle(TableStyle([
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('ALIGN', (3,0), (3,-1), 'RIGHT'),
        ('FONTNAME', (2,2), (3,2), 'Helvetica-Bold'),
        ('FONTSIZE', (2,2), (3,2), 12),
    ]))
    
    elements.append(t2)
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("<i>Computer Generated Invoice. Authorised Signatory not required.</i>", styles['Normal']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response = Response(pdf, mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=Invoice_{bill_id}.pdf'
    return response
