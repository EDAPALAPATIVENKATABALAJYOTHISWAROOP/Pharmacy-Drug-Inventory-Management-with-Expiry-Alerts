from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'danger')
                return redirect(url_for('auth.login'))
            if role and session.get('role') != role and session.get('role') != 'Admin':
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        from app import get_db
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            
            flash(f"Welcome back, {user['full_name']}!", 'success')
            if user['role'] == 'Admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('inventory.list_drugs'))
        else:
            flash('Invalid username or password', 'danger')
            
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['POST'])
def register():
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    role = request.form.get('role', 'Pharmacist')

    # Validate role
    if role not in ('Admin', 'Pharmacist'):
        role = 'Pharmacist'

    if not full_name or not username or not password:
        flash('All fields are required.', 'danger')
        return redirect(url_for('auth.login') + '?tab=signup')

    if password != confirm_password:
        flash('Passwords do not match. Please try again.', 'danger')
        return redirect(url_for('auth.login') + '?tab=signup')

    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('auth.login') + '?tab=signup')

    from app import get_db
    db = get_db()
    cur = db.cursor()

    # Check duplicate username
    cur.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        flash(f'Username "{username}" is already taken. Please choose another.', 'danger')
        return redirect(url_for('auth.login') + '?tab=signup')

    password_hash = generate_password_hash(password)
    cur.execute(
        "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, full_name)
    )
    db.commit()

    flash(f'Account created successfully! Welcome, {full_name}. Please sign in.', 'success')
    return redirect(url_for('auth.login'))

