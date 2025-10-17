import os
import json
import tempfile
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, abort
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from hdfs import InsecureClient  # HDFS client library
import mimetypes
import secrets  # For secure secret key generation


# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(minutes=10)

hdfs_client = InsecureClient(os.getenv("HDFS_NAMENODE"), os.getenv("HDFS_USER"))


# Database connection function
def create_connection():
    """Establishes a connection to the MySQL database."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def upload_file_to_hdfs(local_path, hdfs_path):
    with open(local_path, 'rb') as local_file:
        hdfs_client.write(hdfs_path, local_file, overwrite=True)

def delete_file_from_hdfs(hdfs_path):
    if hdfs_client.status(hdfs_path, strict=False):
        hdfs_client.delete(hdfs_path)


def generate_analytics_data():
    """
    Connects to the database, calculates key metrics, and saves them to HDFS.
    """
    print("Starting analytics data generation...")
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    
    analytics_data = {}

    try:
        # 1. Total Transaction Value
        cursor.execute("SELECT SUM(amount) AS total_transactions FROM PAYMENTS WHERE payment_status = 'completed'")
        total_transactions = cursor.fetchone()['total_transactions']
        analytics_data['total_transactions'] = float(total_transactions) if total_transactions else 0.0

        # 2. Number of Users (excluding admins)
        cursor.execute("SELECT COUNT(user_id) AS user_count FROM USERS WHERE role = 'user'")
        user_count = cursor.fetchone()['user_count']
        analytics_data['user_count'] = user_count if user_count else 0

        # 3. Number of Rooms Booked (confirmed or completed)
        cursor.execute("SELECT COUNT(booking_id) AS bookings_count FROM BOOKINGS WHERE booking_status IN ('confirmed', 'completed')")
        bookings_count = cursor.fetchone()['bookings_count']
        analytics_data['bookings_count'] = bookings_count if bookings_count else 0
        
        # 4. Monthly Trend (Number of bookings per month)
        cursor.execute("""
            SELECT 
                DATE_FORMAT(check_in_date, '%Y-%m') AS month,
                COUNT(booking_id) AS count
            FROM BOOKINGS
            WHERE booking_status IN ('confirmed', 'completed')
            GROUP BY month
            ORDER BY month ASC
        """)
        monthly_trend = cursor.fetchall()
        analytics_data['monthly_trend'] = monthly_trend

        # Convert the dictionary to a JSON string
        json_data = json.dumps(analytics_data, indent=4)
        
        # Define the HDFS path
        hdfs_path = '/staynngo/analytics/summary.json'
        
        # Write the JSON data to HDFS
        hdfs_client.write(hdfs_path, data=json_data.encode('utf-8'), overwrite=True)
        
        print(f"Analytics data successfully generated and saved to HDFS at {hdfs_path}")

    except mysql.connector.Error as err:
        print(f"Database error during analytics generation: {err}")
    except Exception as e:
        print(f"An error occurred during analytics generation: {e}")
    finally:
        conn.close()


# Function to check for completed bookings and update room availability
def update_room_availability():
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    current_time = datetime.now()
    try:
        cursor.execute("SELECT room_id FROM BOOKINGS WHERE check_out_date <= %s AND booking_status = 'confirmed'", (current_time,))
        expired_bookings = cursor.fetchall()
        for booking in expired_bookings:
            cursor.execute("UPDATE ROOMS SET availability_status = TRUE WHERE room_id = %s", (booking['room_id'],))
            cursor.execute("UPDATE BOOKINGS SET booking_status = 'completed' WHERE room_id = %s AND check_out_date <= %s AND booking_status = 'confirmed'", (booking['room_id'], current_time))
        if expired_bookings:
            conn.commit()
    except mysql.connector.Error as err:
        print(f"Error updating room availability: {err}")
    finally:
        conn.close()

# Initialize and start the scheduler
scheduler = BackgroundScheduler()
try:
    scheduler.start()
except Exception as e:
    print(f"Failed to start the scheduler: {e}")

scheduler.add_job(func=update_room_availability, trigger="interval", hours=1)
# NOTE: The interval below is set for frequent testing. Change to a larger value (e.g., hours=24) for production.
scheduler.add_job(func=generate_analytics_data, trigger="interval", seconds=10)


# --- CORE NAVIGATIONAL ROUTES ---

@app.route('/')
def landing():
    """Renders the main informational landing page."""
    return render_template('landing.html')

@app.route('/auth')
def auth():
    """Renders the page with login and registration forms."""
    return render_template('login_register.html')


# --- AUTHENTICATION ROUTES ---

@app.route('/register', methods=['POST'])
def register():
    """Handles user registration."""
    conn = create_connection()
    cursor = conn.cursor()
    name = request.form['name']
    email = request.form['email']
    password = generate_password_hash(request.form['password'])
    role = request.form['role']
    phone_number = request.form['phone_number']
    
    try:
        cursor.execute("INSERT INTO USERS (name, email, password, role, phone_number) VALUES (%s, %s, %s, %s, %s)", 
                       (name, email, password, role, phone_number))
        conn.commit()
        flash("Account created successfully! Please log in.")
    except mysql.connector.Error as err:
        flash(f"Error: {err}")
    finally:
        conn.close()
    return redirect(url_for('auth'))

@app.route('/login', methods=['POST'])
def login():
    """Handles user login and redirects based on role."""
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    email = request.form['email']
    password = request.form['password']
    role = request.form['role']
    
    cursor.execute("SELECT * FROM USERS WHERE email=%s AND role=%s", (email, role))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['logged_in'] = True
        session['user_id'] = user['user_id']
        session['name'] = user['name']
        session['role'] = user['role']
        flash("Logged in successfully.")
        
        if session['role'] == 'admin':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
    else:
        flash("Login failed. Check your credentials and try again.")
        return redirect(url_for('auth'))

@app.route('/logout')
def logout():
    """Logs the user out and clears the session."""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('landing'))


# --- DASHBOARD ROUTES ---

@app.route('/dashboard')
def dashboard():
    """Displays the admin dashboard for viewing and managing properties."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM PROPERTIES WHERE owner_id = %s", (session['user_id'],))
        properties = cursor.fetchall()
        conn.close()
        return render_template('dashboard.html', properties=properties, name=session['name'], role=session['role'])
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/user_dashboard')
def user_dashboard():
    """Displays a list of available properties for regular users."""
    if 'logged_in' in session and session['role'] == 'user':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM PROPERTIES")
        properties = cursor.fetchall()
        conn.close()
        return render_template('user_dashboard.html', properties=properties, name=session['name'], role=session['role'])
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/analytics')
def admin_analytics():
    """Displays the analytics dashboard for admins by fetching data from HDFS."""
    if 'logged_in' not in session or session['role'] != 'admin':
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

    hdfs_path = '/staynngo/analytics/summary.json'
    stats = {
        'total_transactions': 0, 'user_count': 0, 'bookings_count': 0, 'monthly_trend': []
    }
    
    try:
        if hdfs_client.status(hdfs_path, strict=False):
            with hdfs_client.read(hdfs_path) as reader:
                stats = json.load(reader)
        else:
            flash("Analytics data is not yet generated. It will be available after the next scheduled run.")
    except Exception as e:
        print(f"Error reading analytics data from HDFS: {e}")
        flash("Could not retrieve analytics data. Please check the logs.")
    
    monthly_trend = stats.get('monthly_trend', [])
    chart_labels = [item['month'] for item in monthly_trend]
    chart_values = [item['count'] for item in monthly_trend]

    return render_template('analytics.html', 
                           stats=stats,
                           chart_labels=json.dumps(chart_labels), 
                           chart_values=json.dumps(chart_values))


# --- USER BOOKING AND VIEWING ROUTES ---

@app.route('/book_room/<int:room_id>/<int:property_id>', methods=['GET', 'POST'])
def book_room(room_id, property_id):
    if 'logged_in' not in session or session['role'] != 'user':
        flash("Please log in to make a booking.")
        return redirect(url_for('auth'))

    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM ROOMS WHERE room_id = %s", (room_id,))
    room = cursor.fetchone()

    if not room or not room['availability_status']:
        flash("This room is currently unavailable.")
        conn.close()
        return redirect(url_for('view_more', property_id=property_id))

    if request.method == 'POST':
        check_in_date = request.form['check_in_date']
        check_out_date = request.form['check_out_date']
        payment_method = request.form['payment_method']
        user_id = session['user_id']

        check_in = datetime.strptime(check_in_date, '%Y-%m-%d')
        check_out = datetime.strptime(check_out_date, '%Y-%m-%d')
        num_days = (check_out - check_in).days

        if num_days <= 0:
            flash("Check-out date must be after the check-in date.")
            conn.close()
            return render_template('booking.html', room=room, property_id=property_id)
            
        total_price = num_days * room['price_per_night']

        try:
            cursor.execute("INSERT INTO BOOKINGS (user_id, room_id, check_in_date, check_out_date, total_price, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())", (user_id, room_id, check_in_date, check_out_date, total_price))
            booking_id = cursor.lastrowid
            cursor.execute("INSERT INTO PAYMENTS (booking_id, payment_method, amount, payment_status, payment_date) VALUES (%s, %s, %s, 'completed', NOW())", (booking_id, payment_method, total_price))
            cursor.execute("UPDATE ROOMS SET availability_status = 0 WHERE room_id = %s", (room_id,))
            conn.commit()
            flash("Booking and payment successful!")
            return redirect(url_for('user_dashboard'))
        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Error: {err}")
        finally:
            conn.close()
    else:
        conn.close()
    
    return render_template('booking.html', room=room, property_id=property_id)

@app.route('/view_more/<int:property_id>')
def view_more(property_id):
    if 'logged_in' not in session or session['role'] != 'user':
        flash("Please log in to view property details.")
        return redirect(url_for('auth'))
        
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s", (property_id,))
    property_details = cursor.fetchone()
    
    cursor.execute("SELECT * FROM AMENITIES WHERE property_id = %s", (property_id,))
    amenities = cursor.fetchall()
    
    cursor.execute("SELECT * FROM ROOMS WHERE property_id = %s", (property_id,))
    rooms = cursor.fetchall()
    
    room_reviews = {}
    for room in rooms:
        cursor.execute("SELECT r.rating, r.comment, u.name AS user_name, r.created_at FROM REVIEWS r JOIN USERS u ON r.user_id = u.user_id WHERE r.room_id = %s ORDER BY r.created_at DESC", (room['room_id'],))
        room_reviews[room['room_id']] = cursor.fetchall()

    conn.close()
    
    return render_template('view_more.html', property=property_details, amenities=amenities, rooms=rooms, room_reviews=room_reviews)

@app.route('/add_review/<int:room_id>', methods=['POST'])
def add_review(room_id):
    if 'user_id' not in session:
        flash("Please log in to leave a review.")
        return redirect(url_for('auth'))

    user_id = session['user_id']
    rating = int(request.form['rating'])
    comment = request.form['comment']
    created_at = datetime.now()
    property_id = request.form.get('property_id')

    conn = create_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO REVIEWS (room_id, user_id, rating, comment, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)", (room_id, user_id, rating, comment, created_at, created_at))
        conn.commit()
        flash("Your review has been added.")
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        flash("An error occurred. Please try again.")
    finally:
        conn.close()

    return redirect(url_for('view_more', property_id=property_id))

@app.route('/my_bookings')
def my_bookings():
    if 'logged_in' not in session or session['role'] != 'user':
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))
        
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT b.booking_id, b.check_in_date, b.check_out_date, b.total_price, r.room_type, p.address FROM BOOKINGS b JOIN ROOMS r ON b.room_id = r.room_id JOIN PROPERTIES p ON r.property_id = p.property_id WHERE b.user_id = %s", (session['user_id'],))
    bookings = cursor.fetchall()
    conn.close()
    
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/cancel_booking/<int:booking_id>', methods=['POST'])
def cancel_booking(booking_id):
    if 'logged_in' not in session or session['role'] != 'user':
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))
        
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM BOOKINGS WHERE booking_id = %s AND user_id = %s", (booking_id, session['user_id']))
        booking = cursor.fetchone()

        if booking:
            cursor.execute("DELETE FROM PAYMENTS WHERE booking_id = %s", (booking_id,))
            cursor.execute("UPDATE ROOMS SET availability_status = 1 WHERE room_id = %s", (booking['room_id'],))
            cursor.execute("DELETE FROM BOOKINGS WHERE booking_id = %s", (booking_id,))
            conn.commit()
            flash("Booking has been successfully canceled.")
        else:
            flash("Booking not found or you do not have permission to cancel it.")
    except mysql.connector.Error as err:
        conn.rollback()
        flash(f"Error: {err}")
    finally:
        conn.close()

    return redirect(url_for('my_bookings'))


# --- ADMIN CRUD ROUTES (PROPERTIES, AMENITIES, ROOMS) ---

@app.route('/hdfs_image')
def hdfs_image_proxy():
    hdfs_path = request.args.get('hdfs_path')
    if not hdfs_path:
        abort(400, "Missing hdfs_path parameter")
    try:
        mime_type, _ = mimetypes.guess_type(hdfs_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        with hdfs_client.read(hdfs_path) as reader:
            image_data = reader.read()
        return Response(image_data, content_type=mime_type)
    except Exception as e:
        print(f"Error streaming HDFS file {hdfs_path}: {e}")
        abort(404, "Image not found or an error occurred.")

# Property Routes
@app.route('/add_property', methods=['GET', 'POST'])
def add_property():
    if 'logged_in' in session and session['role'] == 'admin':
        if request.method == 'POST':
            conn = create_connection()
            cursor = conn.cursor()
            owner_id = session['user_id']
            address = request.form['address']
            city = request.form['city']
            state = request.form['state']
            country = request.form['country']
            description = request.form['description']

            file = request.files.get('image_file')
            if file and file.filename != '':
                local_path = os.path.join(tempfile.gettempdir(), file.filename)
                file.save(local_path)
                hdfs_path = f"/staynngo/property_images/{file.filename}"
                upload_file_to_hdfs(local_path, hdfs_path)
                os.remove(local_path)
            else:
                hdfs_path = None

            image_description = request.form.get('image_description')

            cursor.execute("INSERT INTO PROPERTIES (owner_id, address, city, state, country, description, image_url, image_description) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                           (owner_id, address, city, state, country, description, hdfs_path, image_description))
            conn.commit()
            property_id = cursor.lastrowid
            conn.close()
            flash("Property added successfully! Now add amenities.")
            return redirect(url_for('add_amenities', property_id=property_id))
        return render_template('add_property.html')
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/edit_property/<int:property_id>', methods=['GET', 'POST'])
def edit_property(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", (property_id, session['user_id']))
        property_item = cursor.fetchone()

        if request.method == 'POST':
            address = request.form['address']
            city = request.form['city']
            state = request.form['state']
            country = request.form['country']
            description = request.form['description']
            image_description = request.form['image_description']

            file = request.files.get('image_file')
            if file and file.filename != '':
                if property_item['image_url']:
                    delete_file_from_hdfs(property_item['image_url'])
                local_path = os.path.join(tempfile.gettempdir(), file.filename)
                file.save(local_path)
                hdfs_path = f"/staynngo/property_images/{file.filename}"
                upload_file_to_hdfs(local_path, hdfs_path)
                os.remove(local_path)
            else:
                hdfs_path = property_item['image_url']
 
            cursor.execute("UPDATE PROPERTIES SET address = %s, city = %s, state = %s, country = %s, description = %s, image_url = %s, image_description = %s WHERE property_id = %s AND owner_id = %s",
                           (address, city, state, country, description, hdfs_path, image_description, property_id, session['user_id']))
            conn.commit()
            conn.close()
            flash("Property updated successfully!")
            return redirect(url_for('dashboard'))

        conn.close()
        return render_template('edit_property.html', property=property_item)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/delete_property/<int:property_id>', methods=['POST'])
def delete_property(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        try:
            conn.start_transaction()
            cursor.execute("DELETE FROM ROOMS WHERE property_id = %s", (property_id,))
            cursor.execute("DELETE FROM AMENITIES WHERE property_id = %s", (property_id,))
            cursor.execute("DELETE FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", (property_id, session['user_id']))
            
            if cursor.rowcount == 0:
                conn.rollback()
                flash("Property not found or you don't have permission to delete it.")
            else:
                conn.commit()
                flash("Property and its associated rooms and amenities were deleted successfully!")
        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Error deleting property: {err}")
        finally:
            conn.close()
        return redirect(url_for('dashboard'))
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

# Amenity Routes
@app.route('/add_amenities/<int:property_id>', methods=['GET', 'POST'])
def add_amenities(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        if request.method == 'POST':
            conn = create_connection()
            cursor = conn.cursor()
            amenity_name = request.form['amenity_name']
            amenity_description = request.form['amenity_description']
            cursor.execute("INSERT INTO AMENITIES (property_id, name, description) VALUES (%s, %s, %s)",
                           (property_id, amenity_name, amenity_description))
            conn.commit()
            conn.close()
            flash("Amenity added successfully!")
            return redirect(url_for('add_amenities', property_id=property_id))
        return render_template('add_amenities.html', property_id=property_id)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/view_amenities/<int:property_id>')
def view_amenities(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM AMENITIES WHERE property_id = %s", (property_id,))
        amenities = cursor.fetchall()
        conn.close()
        return render_template('view_amenities.html', amenities=amenities, property_id=property_id)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/edit_amenity/<int:amenity_id>', methods=['GET', 'POST'])
def edit_amenity(amenity_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM AMENITIES WHERE amenity_id = %s", (amenity_id,))
        amenity = cursor.fetchone()
        
        if request.method == 'POST':
            amenity_name = request.form['amenity_name']
            amenity_description = request.form['amenity_description']
            cursor.execute("UPDATE AMENITIES SET name = %s, description = %s WHERE amenity_id = %s",
                           (amenity_name, amenity_description, amenity_id))
            conn.commit()
            conn.close()
            flash("Amenity updated successfully!")
            return redirect(url_for('view_amenities', property_id=amenity['property_id']))
        
        conn.close()
        return render_template('edit_amenity.html', amenity=amenity)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/delete_amenity/<int:amenity_id>', methods=['POST'])
def delete_amenity(amenity_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM AMENITIES WHERE amenity_id = %s", (amenity_id,))
            conn.commit()
            flash("Amenity deleted successfully!")
        except mysql.connector.Error as err:
            flash(f"Error deleting amenity: {err}")
        finally:
            conn.close()
        return redirect(url_for('view_amenities', property_id=request.form['property_id']))
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

# Room Routes
@app.route('/add_room/<int:property_id>', methods=['GET', 'POST'])
def add_room(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        if request.method == 'POST':
            conn = create_connection()
            cursor = conn.cursor()
            room_type = request.form['room_type']
            capacity = request.form['capacity']
            price_per_night = request.form['price_per_night']
            availability_status = 'availability_status' in request.form
            
            cursor.execute("INSERT INTO ROOMS (property_id, room_type, capacity, price_per_night, availability_status) VALUES (%s, %s, %s, %s, %s)",
                           (property_id, room_type, capacity, price_per_night, availability_status))
            conn.commit()
            conn.close()
            flash("Room added successfully!")
            return redirect(url_for('view_rooms', property_id=property_id))
        
        return render_template('add_rooms.html', property_id=property_id)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/view_rooms/<int:property_id>')
def view_rooms(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ROOMS WHERE property_id = %s", (property_id,))
        rooms = cursor.fetchall()
        conn.close()
        return render_template('view_rooms.html', rooms=rooms, property_id=property_id)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/edit_room/<int:room_id>', methods=['GET', 'POST'])
def edit_room(room_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ROOMS WHERE room_id = %s", (room_id,))
        room = cursor.fetchone()
        
        if request.method == 'POST':
            room_type = request.form['room_type']
            capacity = request.form['capacity']
            price_per_night = request.form['price_per_night']
            availability_status = 'availability_status' in request.form
            
            cursor.execute("UPDATE ROOMS SET room_type = %s, capacity = %s, price_per_night = %s, availability_status = %s WHERE room_id = %s",
                           (room_type, capacity, price_per_night, availability_status, room_id))
            conn.commit()
            conn.close()
            flash("Room updated successfully!")
            return redirect(url_for('view_rooms', property_id=room['property_id']))
        
        conn.close()
        return render_template('edit_rooms.html', room=room)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))

@app.route('/delete_room/<int:room_id>', methods=['POST'])
def delete_room(room_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM ROOMS WHERE room_id = %s", (room_id,))
            conn.commit()
            flash("Room deleted successfully!")
        except mysql.connector.Error as err:
            flash(f"Error deleting room: {err}")
        finally:
            conn.close()
        return redirect(url_for('view_rooms', property_id=request.form['property_id']))
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))
        
@app.route('/room_status/<int:property_id>')
def room_status(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", (property_id, session['user_id']))
        property_details = cursor.fetchone()

        if not property_details:
            flash("Property not found or you do not have permission to view it.")
            conn.close()
            return redirect(url_for('dashboard'))

        cursor.execute("""
            SELECT r.room_id, r.room_type, r.capacity, r.price_per_night, r.availability_status,
                   b.booking_id, b.check_in_date, b.check_out_date, u.name as guest_name
            FROM ROOMS r
            LEFT JOIN BOOKINGS b ON r.room_id = b.room_id AND b.booking_status = 'confirmed'
            LEFT JOIN USERS u ON b.user_id = u.user_id
            WHERE r.property_id = %s
        """, (property_id,))
        rooms = cursor.fetchall()
        
        conn.close()
        return render_template('room_status.html', property=property_details, rooms=rooms)
    else:
        flash("Unauthorized access. Please log in.")
        return redirect(url_for('auth'))


# --- APP SHUTDOWN AND RUN ---

@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    app.run(debug=True)