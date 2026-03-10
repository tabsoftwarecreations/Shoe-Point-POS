import os
import sys
import socket
import qrcode
import urllib.parse
import webbrowser
import subprocess
from datetime import datetime
from threading import Timer
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# === CRITICAL SHOP SETTINGS ===
SHOP_UPI_ID = "7619574995@ibl"
SHOP_NAME = "Shoe Point"
# ==============================

# --- 1. ADD THIS FUNCTION ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Fallback to the folder where app.py actually lives
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- 2. UPDATE YOUR FLASK APP TO USE IT ---
app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))

# --- 3. SET THE DATABASE TO STAY WITH THE EXE ---
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

db_path = os.path.join(application_path, 'shoepoint.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['UPLOAD_FOLDER'] = resource_path('static')
app.secret_key = 'SHOE_POINT_SECURE_KEY_2026'

db = SQLAlchemy(app)

external_qr_folder = os.path.join(application_path, 'qrcodes')
if not os.path.exists(external_qr_folder):
    os.makedirs(external_qr_folder)

# ... (keep the rest of your app.py code the same starting from get_local_ip) ...

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

CIPHER = {'1':'S','2':'O','3':'U','4':'T','5':'H','6':'B','7':'R','8':'A','9':'N','0':'D'}
def encode_price(price):
    return "".join([CIPHER[d] for d in str(int(price))])

customer_display_state = {"active": False, "amount": 0, "qr_url": "", "batch_no": ""}

# ── Database Models ──
class Owner(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    password_hash = db.Column(db.String(128))

class Shoe(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    batch_no   = db.Column(db.String(50), unique=True, nullable=False)
    supplier   = db.Column(db.String(50))
    material   = db.Column(db.String(50))
    cost_price = db.Column(db.Float, nullable=False)
    quantity   = db.Column(db.Integer, default=1)

class Sale(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    batch_no       = db.Column(db.String(50))
    sell_price     = db.Column(db.Float)
    profit         = db.Column(db.Float)
    payment_method = db.Column(db.String(20))
    date           = db.Column(db.DateTime, default=datetime.now)

# ── Routes ──
@app.route('/')
def index():
    shoes     = Shoe.query.filter(Shoe.quantity > 0).all()
    low_stock = Shoe.query.filter(Shoe.quantity > 0, Shoe.quantity < 3).all()
    local_ip  = get_local_ip()
    mobile_url  = f"http://{local_ip}:5000"
    display_url = f"http://{local_ip}:5000/customer_screen"
    
    # --- FIXED: Use app.static_folder instead of STATIC_DIR ---
    if not os.path.exists(app.static_folder):
        os.makedirs(app.static_folder)
        
    qr_mobile = qrcode.QRCode(box_size=4, border=2)
    qr_mobile.add_data(mobile_url)
    qr_mobile.make(fit=True)
    qr_mobile.make_image(fill_color="black", back_color="white").save(os.path.join(app.static_folder, 'mobile_connect.png'))
    
    qr_display = qrcode.QRCode(box_size=4, border=2)
    qr_display.add_data(display_url)
    qr_display.make(fit=True)
    qr_display.make_image(fill_color="black", back_color="white").save(os.path.join(app.static_folder, 'display_connect.png'))
    
    return render_template('index.html', shoes=shoes, low_stock=low_stock, mobile_url=mobile_url, display_url=display_url)

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if Owner.query.first(): return redirect(url_for('login'))
    if request.method == 'POST':
        if request.form['password'] != request.form['confirm']:
            flash("Passwords do not match!", "error")
            return render_template('setup.html')
        hashed_pw = generate_password_hash(request.form['password'])
        db.session.add(Owner(password_hash=hashed_pw))
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not Owner.query.first(): return redirect(url_for('setup'))
    if request.method == 'POST':
        owner = Owner.query.first()
        if owner and check_password_hash(owner.password_hash, request.form['password']):
            session['logged_in'] = True
            return redirect(url_for('owner_dashboard'))
        else:
            flash('Invalid Password!', "error")
    return render_template('login.html')
@app.route('/backup_db')
def backup_db():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    try:
        # Generate a timestamped filename
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        backup_filename = f"ShoePoint_Backup_{timestamp}.db"
        
        # Send the database file to the user as a download
        import flask
        return flask.send_file(db_path, as_attachment=True, download_name=backup_filename)
    except Exception as e:
        flash(f"Backup Error: Could not generate backup file.", "error")
        return redirect(url_for('owner_dashboard'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/owner')
def owner_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    low_stock = Shoe.query.filter(Shoe.quantity < 3).all()
    today = datetime.now().date()
    daily_sales  = Sale.query.filter(db.func.date(Sale.date) == today).all()
    daily_profit = sum(s.profit for s in daily_sales)
    total_profit = db.session.query(db.func.sum(Sale.profit)).scalar() or 0
    start_date_str = request.args.get('start_date')
    end_date_str   = request.args.get('end_date')
    query          = Sale.query
    filtered_profit = None
    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date   = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        query      = query.filter(Sale.date >= start_date, Sale.date <= end_date)
        sales_in_range  = query.all()
        filtered_profit = sum(s.profit for s in sales_in_range)
    sales = query.order_by(Sale.date.desc()).all()
    return render_template('owner.html', sales=sales, total_profit=total_profit,
                           low_stock=low_stock, daily_profit=daily_profit,
                           start_date=start_date_str, end_date=end_date_str,
                           filtered_profit=filtered_profit)

@app.route('/change_password', methods=['POST'])
def change_password():
    if not session.get('logged_in'): return redirect(url_for('login'))
    owner = Owner.query.first()
    if check_password_hash(owner.password_hash, request.form['old_password']):
        owner.password_hash = generate_password_hash(request.form['new_password'])
        db.session.commit()
        flash('Security Alert: Password updated successfully.', 'success')
    else:
        flash('Authentication Failed: Incorrect current password.', 'error')
    return redirect(url_for('owner_dashboard'))

@app.route('/get_shoe_price/<batch_no>')
def get_shoe_price(batch_no):
    shoe = Shoe.query.filter_by(batch_no=batch_no.strip()).first()
    if shoe: return jsonify({'success': True, 'price': int(shoe.cost_price * 1.60)})
    return jsonify({'success': False})

@app.route('/add_shoe', methods=['POST'])
def add_shoe():
    batch_no = f"{request.form['supplier'].upper()}-{request.form['material'].upper()}-{encode_price(request.form['cost'])}"
    shoe = Shoe.query.filter_by(batch_no=batch_no).first()
    if shoe:
        shoe.quantity += int(request.form.get('quantity', 1))
    else:
        db.session.add(Shoe(
            batch_no=batch_no,
            supplier=request.form['supplier'].upper(),
            material=request.form['material'].upper(),
            cost_price=float(request.form['cost']),
            quantity=int(request.form.get('quantity', 1))
        ))
    db.session.commit()
    qr = qrcode.QRCode(version=1, box_size=2, border=1)
    qr.add_data(batch_no)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(os.path.join(external_qr_folder, f"{batch_no}.png"))
    return redirect(url_for('index'))

@app.route('/sell', methods=['POST'])
def sell_shoe():
    batch_no      = request.form['batch_no'].strip()
    price_input   = request.form.get('sell_price', '').strip()
    discount_input = request.form.get('discount', '0').strip()
    if not price_input: return "Error: Price cannot be empty!", 400
    try:
        base_price  = float(price_input)
        discount    = float(discount_input) if discount_input else 0.0
        final_price = base_price - discount
    except ValueError:
        return "Error: Invalid Numeric Input!", 400
    pay_method = request.form.get('payment_method')
    shoe = Shoe.query.filter_by(batch_no=batch_no).first()
    if shoe and shoe.quantity > 0:
        if pay_method == "Cash":
            shoe.quantity -= 1
            profit = final_price - shoe.cost_price
            db.session.add(Sale(batch_no=batch_no, sell_price=final_price, profit=profit, payment_method="Cash"))
            db.session.commit()
            flash('Transaction Complete: Cash Payment recorded.', 'success')
            return redirect(url_for('index'))
        elif pay_method == "UPI":
            upi_link = f"upi://pay?pa={SHOP_UPI_ID}&pn={urllib.parse.quote(SHOP_NAME)}&am={final_price}&cu=INR"
            qrcode.make(upi_link).save(os.path.join(external_qr_folder, "last_payment.png"))
            customer_display_state.update({"active": True, "amount": final_price, "qr_url": "last_payment.png", "batch_no": batch_no})
            return render_template('payment.html', qr_url="last_payment.png", amount=final_price, batch_no=batch_no)
    return "Error: Product not found or out of stock.", 404

@app.route('/confirm_upi_sale', methods=['POST'])
def confirm_upi_sale():
    batch_no   = request.form['batch_no']
    sell_price = float(request.form['amount'])
    shoe = Shoe.query.filter_by(batch_no=batch_no).first()
    if shoe and shoe.quantity > 0:
        shoe.quantity -= 1
        profit = sell_price - shoe.cost_price
        db.session.add(Sale(batch_no=batch_no, sell_price=sell_price, profit=profit, payment_method="UPI"))
        db.session.commit()
        customer_display_state["active"] = False
        flash('Transaction Complete: UPI Payment verified.', 'success')
        return redirect(url_for('index'))
    return "Error: Stock discrepancy during transaction.", 400

@app.route('/cancel_upi_sale')
def cancel_upi_sale():
    customer_display_state["active"] = False
    return redirect(url_for('index'))

@app.route('/return_item', methods=['POST'])
def return_item():
    batch_no   = request.form['batch_no'].strip()
    shoe       = Shoe.query.filter_by(batch_no=batch_no).first()
    last_sale  = Sale.query.filter_by(batch_no=batch_no).order_by(Sale.date.desc()).first()
    if shoe:
        shoe.quantity += 1
        if last_sale: db.session.delete(last_sale)
        db.session.commit()
        flash(f'Return Processed: Batch {batch_no} returned to inventory.', 'success')
    else:
        flash('Return Failed: Batch code not recognized.', 'error')
    return redirect(url_for('index'))

@app.route('/api/display_status')
def display_status():
    return jsonify(customer_display_state)

@app.route('/customer_screen')
def customer_screen():
    return render_template('customer.html')

@app.route('/delete_sale/<int:id>')
def delete_sale(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    sale = Sale.query.get_or_404(id)
    db.session.delete(sale)
    db.session.commit()
    return redirect(url_for('owner_dashboard'))

@app.route('/delete_shoe/<int:id>')
def delete_shoe(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    shoe = Shoe.query.get_or_404(id)
    qr_path = os.path.join(external_qr_folder, f"{shoe.batch_no}.png")
    if os.path.exists(qr_path): os.remove(qr_path)
    db.session.delete(shoe)
    db.session.commit()
    flash(f'Item Removed: Batch {shoe.batch_no} deleted from inventory.', 'success')
    return redirect(url_for('owner_dashboard'))

@app.route('/delete_qr/<batch_no>')
def delete_qr(batch_no):
    if not session.get('logged_in'): return redirect(url_for('login'))
    qr_path = os.path.join(external_qr_folder, f"{batch_no}.png")
    if os.path.exists(qr_path):
        os.remove(qr_path)
        flash(f'QR Deleted: Label for {batch_no} has been removed.', 'success')
    else:
        flash(f'QR Not Found: No label file exists for {batch_no}.', 'error')
    return redirect(url_for('index'))

import flask
@app.route('/static/qrcodes/<filename>')
def serve_qr(filename):
    return flask.send_from_directory(external_qr_folder, filename)

# ── Auto-launch browser in App Mode ──
def open_browser():
    url = "http://127.0.0.1:5000"
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    launched = False
    for path in chrome_paths:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, f"--app={url}", "--window-size=1280,800"])
                launched = True
                break
            except Exception:
                pass
    if not launched:
        for path in edge_paths:
            if os.path.exists(path):
                try:
                    subprocess.Popen([path, f"--app={url}", "--window-size=1280,800"])
                    launched = True
                    break
                except Exception:
                    pass
    if not launched:
        webbrowser.open(url)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    Timer(1.5, open_browser).start()
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)