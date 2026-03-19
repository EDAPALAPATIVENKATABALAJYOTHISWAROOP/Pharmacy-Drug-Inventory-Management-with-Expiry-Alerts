from flask import Flask, render_template, session, redirect, url_for, g
import sqlite3
from config import Config
import datetime
import os

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(Config.DATABASE_PATH)
        db.row_factory = sqlite3.Row
    return db

def init_db(app):
    with app.app_context():
        db = get_db()
        with app.open_resource('database/schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Automatically create DB and tables if doesn't exist
    if not os.path.exists(Config.DATABASE_PATH):
        init_db(app)
        
    try:
        from database.seeder import seed_db
        seed_db(app)
    except Exception as e:
        print(f"Seeder failed: {e}")

    @app.teardown_appcontext
    def close_connection(exception):
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()

    # Register Blueprints
    from blueprints.auth import auth_bp
    from blueprints.inventory import inventory_bp
    from blueprints.billing import billing_bp
    from blueprints.suppliers import suppliers_bp
    from blueprints.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(admin_bp)

    # Context Processor for Expiry Alerts
    @app.context_processor
    def inject_alerts():
        if 'user_id' not in session:
            return dict(expired_count=0, critical_count=0, warning_count=0, low_stock_count=0)
            
        try:
            db = get_db()
            cur = db.cursor()
            
            # Expired Count
            cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE expiry_date < date('now')")
            expired_count = cur.fetchone()['count']
            
            # Critical Count (<= 30 days)
            cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE expiry_date >= date('now') AND expiry_date <= date('now', '+30 days')")
            critical_count = cur.fetchone()['count']
            
            # Warning Count (31 to 90 days)
            cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE expiry_date > date('now', '+30 days') AND expiry_date <= date('now', '+90 days')")
            warning_count = cur.fetchone()['count']
            
            # Low Stock Count
            cur.execute("SELECT COUNT(*) as count FROM drug_batches WHERE quantity <= min_threshold AND quantity > 0")
            low_stock_count = cur.fetchone()['count']
            
            return dict(
                expired_count=expired_count,
                critical_count=critical_count,
                warning_count=warning_count,
                low_stock_count=low_stock_count
            )
        except Exception as e:
            return dict(expired_count=0, critical_count=0, warning_count=0, low_stock_count=0)

    @app.route('/')
    def index():
        if 'user_id' in session:
            if session.get('role') == 'Admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('inventory.list_drugs'))
        return redirect(url_for('auth.login'))

    @app.route('/seed-data')
    def force_seed_route():
        try:
            from database.seeder import seed_db
            seed_db(app)
            return "SUCCESS! 200 items added. <a href='/'>Click here to go back to dashboard</a>"
        except Exception as e:
            return f"Error running seeder: {e}"

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, use_reloader=False)
