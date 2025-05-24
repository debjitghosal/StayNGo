import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(minutes=10)

# Database connection function
def create_connection():
    """Establishes a connection to the MySQL database."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

# Function to check for completed bookings and update room availability
def update_room_availability():
    """Checks for bookings that have reached their check-out date and updates the room availability."""
    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    current_time = datetime.now()

    try:
        # Select bookings that have reached their check-out date and are still marked as active
        cursor.execute("""
            SELECT room_id 
            FROM BOOKINGS 
            WHERE check_out_date <= %s
        """, (current_time,))

        expired_bookings = cursor.fetchall()

        for booking in expired_bookings:
            # Update room availability to make it available again
            cursor.execute("""
                UPDATE ROOMS 
                SET availability_status = 1 
                WHERE room_id = %s
            """, (booking['room_id'],))

        # Commit the changes if there were any updates
        if expired_bookings:
            conn.commit()
            print(f"Updated availability for {len(expired_bookings)} room(s).")

    except mysql.connector.Error as err:
        print(f"Error updating room availability: {err}")
    finally:
        conn.close()

# Initialize and start the scheduler
scheduler = BackgroundScheduler()

# Start the scheduler and check for any issues
try:
    scheduler.start()
except Exception as e:
    print(f"Failed to start the scheduler: {e}")

scheduler.add_job(func=update_room_availability, trigger="interval", hours=1)

@app.route('/')
def home():
    """Renders the home page with login and registration forms."""
    return render_template('index.html')

# Registration Route
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
    return redirect(url_for('home'))

# Login Route
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
        
        # Redirect to respective dashboard based on role
        if session['role'] == 'admin':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
    else:
        flash("Login failed. Check your credentials and try again.")
        return redirect(url_for('home'))

# Admin Dashboard Route
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
        flash("Unauthorized access.")
        return redirect(url_for('home'))

# User Dashboard Route
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
        flash("Unauthorized access.")
        return redirect(url_for('home'))
@app.route('/book_room/<int:room_id>/<int:property_id>', methods=['GET', 'POST'])
def book_room(room_id, property_id):
    """Handles the booking process, checks room availability, and updates availability status after booking with payment processing."""
    if 'logged_in' not in session or session['role'] != 'user':
        flash("Please log in to make a booking.")
        return redirect(url_for('login'))

    conn = create_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch room details for price and availability check
    cursor.execute("SELECT * FROM ROOMS WHERE room_id = %s", (room_id,))
    room = cursor.fetchone()

    # Check if room is available
    if not room['availability_status']:
        flash("This room is currently unavailable.")
        conn.close()
        return redirect(url_for('view_more', property_id=property_id))

    if request.method == 'POST':
        check_in_date = request.form['check_in_date']
        check_out_date = request.form['check_out_date']
        payment_method = request.form['payment_method']
        user_id = session['user_id']

        # Calculate the total price based on the number of days
        check_in = datetime.strptime(check_in_date, '%Y-%m-%d')
        check_out = datetime.strptime(check_out_date, '%Y-%m-%d')
        num_days = (check_out - check_in).days
        total_price = num_days * room['price_per_night']

        # Begin transaction for booking and payment
        try:
            # Insert into BOOKINGS table
            cursor.execute("""
                INSERT INTO BOOKINGS (user_id, room_id, check_in_date, check_out_date, total_price, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (user_id, room_id, check_in_date, check_out_date, total_price))
            booking_id = cursor.lastrowid

            # Insert into PAYMENTS table
            cursor.execute("""
                INSERT INTO PAYMENTS (booking_id, payment_method, amount, payment_status, payment_date)
                VALUES (%s, %s, %s, 'completed', NOW())
            """, (booking_id, payment_method, total_price))

            # Update the room's availability status to "unavailable"
            cursor.execute("""
                UPDATE ROOMS
                SET availability_status = 0
                WHERE room_id = %s
            """, (room_id,))

            # Commit the transaction
            conn.commit()
            flash("Booking and payment successful!")
            return redirect(url_for('user_dashboard'))
        except mysql.connector.Error as err:
            conn.rollback()  # Rollback the transaction in case of an error
            flash(f"Error: {err}")
        finally:
            conn.close()

    conn.close()
    return render_template('booking.html', room=room, property_id=property_id)

@app.route('/room_status/<int:property_id>')
def room_status(property_id):
    """Displays the status of rooms for a specific property to show if they are booked or available."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch property details
        cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", (property_id, session['user_id']))
        property_details = cursor.fetchone()

        if not property_details:
            flash("Property not found or you do not have permission to view it.")
            conn.close()
            return redirect(url_for('dashboard'))

        # Fetch room status details
        cursor.execute("""
            SELECT r.room_id, r.room_type, r.capacity, r.price_per_night,
                   CASE WHEN b.booking_id IS NOT NULL THEN 1 ELSE 0 END AS is_booked
            FROM ROOMS r
            LEFT JOIN BOOKINGS b ON r.room_id = b.room_id AND b.check_out_date >= CURDATE()
            WHERE r.property_id = %s
        """, (property_id,))
        rooms = cursor.fetchall()
        
        conn.close()

        return render_template('room_status.html', property=property_details, rooms=rooms)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))


# Route for viewing more details about a specific property
@app.route('/view_more/<int:property_id>')
def view_more(property_id):
    if 'logged_in' in session and session['role'] == 'user':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch property details
        cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s", (property_id,))
        property_details = cursor.fetchone()
        
        # Fetch amenities
        cursor.execute("SELECT * FROM AMENITIES WHERE property_id = %s", (property_id,))
        amenities = cursor.fetchall()
        
        # Fetch rooms and their respective reviews
        cursor.execute("SELECT * FROM ROOMS WHERE property_id = %s", (property_id,))
        rooms = cursor.fetchall()
        
        # Fetch reviews for each room and group them by room_id
        room_reviews = {}
        for room in rooms:
            cursor.execute("""
                SELECT r.rating, r.comment, u.name AS user_name, r.created_at
                FROM REVIEWS r
                JOIN USERS u ON r.user_id = u.user_id
                WHERE r.room_id = %s
                ORDER BY r.created_at DESC
            """, (room['room_id'],))
            room_reviews[room['room_id']] = cursor.fetchall()

        conn.close()
        
        # Pass reviews for each room along with other property details
        return render_template('view_more.html', property=property_details, amenities=amenities, rooms=rooms, room_reviews=room_reviews)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))

# Route to add a review for a specific room
@app.route('/add_review/<int:room_id>', methods=['POST'])
def add_review(room_id):
    if 'user_id' not in session:
        flash("Please log in to leave a review.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    rating = int(request.form['rating'])
    comment = request.form['comment']
    created_at = datetime.now()
    property_id = request.form.get('property_id')  # Get the property_id to redirect back to view_more page

    conn = create_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO REVIEWS (room_id, user_id, rating, comment, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (room_id, user_id, rating, comment, created_at, created_at))
        conn.commit()
        flash("Your review has been added.")
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        flash("An error occurred. Please try again.")
    finally:
        conn.close()

    # Redirect back to the property details page with the specific room reviews section
    return redirect(url_for('view_more', property_id=property_id))


@app.route('/my_bookings')
def my_bookings():
    """Displays the current bookings of the logged-in user."""
    if 'logged_in' in session and session['role'] == 'user':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Query for user's bookings
        cursor.execute("""
            SELECT b.booking_id, b.check_in_date, b.check_out_date, b.total_price, r.room_type, p.address 
            FROM BOOKINGS b
            JOIN ROOMS r ON b.room_id = r.room_id
            JOIN PROPERTIES p ON r.property_id = p.property_id
            WHERE b.user_id = %s
        """, (session['user_id'],))
        
        bookings = cursor.fetchall()
        conn.close()
        
        return render_template('my_bookings.html', bookings=bookings)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))

@app.route('/cancel_booking/<int:booking_id>', methods=['POST'])
def cancel_booking(booking_id):
    """Handles the cancellation of a booking by the user."""
    if 'logged_in' in session and session['role'] == 'user':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Fetch the booking details to check if it exists and belongs to the logged-in user
            cursor.execute("SELECT * FROM BOOKINGS WHERE booking_id = %s AND user_id = %s", (booking_id, session['user_id']))
            booking = cursor.fetchone()

            if booking:
                # First, delete the associated payment record
                cursor.execute("DELETE FROM PAYMENTS WHERE booking_id = %s", (booking_id,))

                # Update the room availability status to available (1)
                cursor.execute("UPDATE ROOMS SET availability_status = 1 WHERE room_id = %s", (booking['room_id'],))

                # Then, delete the booking record
                cursor.execute("DELETE FROM BOOKINGS WHERE booking_id = %s", (booking_id,))
                
                conn.commit()  # Commit all the changes together

                flash("Booking has been successfully canceled.")
            else:
                flash("Booking not found or you do not have permission to cancel it.")
        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Error: {err}")
        finally:
            conn.close()

        return redirect(url_for('my_bookings'))
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))


# Delete Property Route
@app.route('/delete_property/<int:property_id>', methods=['POST'])
def delete_property(property_id):
    """Allows admin to delete a property along with associated rooms and amenities."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        
        try:
            # Start a transaction
            conn.start_transaction()
            
            # Delete associated rooms
            cursor.execute("DELETE FROM ROOMS WHERE property_id = %s", (property_id,))
            
            # Delete associated amenities
            cursor.execute("DELETE FROM AMENITIES WHERE property_id = %s", (property_id,))
            
            # Delete the property
            cursor.execute("DELETE FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", 
                           (property_id, session['user_id']))
            
            if cursor.rowcount == 0:
                # Rollback if no property was deleted (no match or permission denied)
                conn.rollback()
                flash("Property not found or you don't have permission to delete it.")
            else:
                # Commit the transaction if all deletions were successful
                conn.commit()
                flash("Property and its associated rooms and amenities were deleted successfully!")
        
        except mysql.connector.Error as err:
            # Rollback in case of any error
            conn.rollback()
            flash(f"Error deleting property: {err}")
        finally:
            # Close the database connection
            conn.close()
        
        return redirect(url_for('dashboard'))
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))


# Other routes (Add, Edit, etc.) remain unchanged    

# Add Property Route
@app.route('/add_property', methods=['GET', 'POST'])
def add_property():
    """Allows admin to add new properties."""
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
            image_url = request.form['image_url']
            image_description = request.form['image_description']
            
            cursor.execute("""INSERT INTO PROPERTIES 
                              (owner_id, address, city, state, country, description, image_url, image_description)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                           (owner_id, address, city, state, country, description, image_url, image_description))
            conn.commit()
            property_id = cursor.lastrowid
            conn.close()
            flash("Property added successfully! Now add amenities.")
            return redirect(url_for('add_amenities', property_id=property_id))
        return render_template('add_property.html')
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))

# Add Amenities Route
@app.route('/add_amenities/<int:property_id>', methods=['GET', 'POST'])
def add_amenities(property_id):
    """Allows admin to add amenities for a specific property."""
    if 'logged_in' in session and session['role'] == 'admin':
        if request.method == 'POST':
            conn = create_connection()
            cursor = conn.cursor()
            amenity_name = request.form['amenity_name']
            amenity_description = request.form['amenity_description']
            
            cursor.execute("""INSERT INTO AMENITIES (property_id, name, description)
                              VALUES (%s, %s, %s)""",
                           (property_id, amenity_name, amenity_description))
            conn.commit()
            conn.close()
            flash("Amenity added successfully!")
            return redirect(url_for('add_amenities', property_id=property_id))
        
        return render_template('add_amenities.html', property_id=property_id)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))

# Edit Property Route
@app.route('/edit_property/<int:property_id>', methods=['GET', 'POST'])
def edit_property(property_id):
    """Allows admin to edit property details."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch the property to be edited
        cursor.execute("SELECT * FROM PROPERTIES WHERE property_id = %s AND owner_id = %s", (property_id, session['user_id']))
        property = cursor.fetchone()

        if request.method == 'POST':
            # Update the property details
            address = request.form['address']
            city = request.form['city']
            state = request.form['state']
            country = request.form['country']
           
            description = request.form['description']
            image_url = request.form['image_url']
            image_description = request.form['image_description']
            
            cursor.execute("""UPDATE PROPERTIES SET address = %s, city = %s, state = %s, country = %s, 
                                description = %s, image_url = %s, image_description = %s
                              WHERE property_id = %s AND owner_id = %s""",
                           (address, city, state, country, description, image_url, image_description, property_id, session['user_id']))
            conn.commit()
            conn.close()
            flash("Property updated successfully!")
            return redirect(url_for('dashboard'))
        
        conn.close()
        return render_template('edit_property.html', property=property)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))
    
# View Amenities Route
@app.route('/view_amenities/<int:property_id>')
def view_amenities(property_id):
    """Displays amenities for a specific property."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM AMENITIES WHERE property_id = %s", (property_id,))
        amenities = cursor.fetchall()
        conn.close()
        return render_template('view_amenities.html', amenities=amenities, property_id=property_id)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))
    
# Delete Amenity Route
@app.route('/delete_amenity/<int:amenity_id>', methods=['POST'])
def delete_amenity(amenity_id):
    """Allows admin to delete an amenity."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        
        try:
            # Delete the amenity
            cursor.execute("DELETE FROM AMENITIES WHERE amenity_id = %s", (amenity_id,))
            conn.commit()
            flash("Amenity deleted successfully!")
        except mysql.connector.Error as err:
            flash(f"Error deleting amenity: {err}")
        finally:
            conn.close()
        
        # Redirect back to the view_amenities page for the associated property
        return redirect(url_for('view_amenities', property_id=request.form['property_id']))
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))


# Edit Amenity Route
@app.route('/edit_amenity/<int:amenity_id>', methods=['GET', 'POST'])
def edit_amenity(amenity_id):
    """Allows admin to edit an amenity."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch the amenity to be edited
        cursor.execute("SELECT * FROM AMENITIES WHERE amenity_id = %s", (amenity_id,))
        amenity = cursor.fetchone()
        
        if request.method == 'POST':
            # Update the amenity details
            amenity_name = request.form['amenity_name']
            amenity_description = request.form['amenity_description']
            
            cursor.execute("""UPDATE AMENITIES SET name = %s, description = %s
                              WHERE amenity_id = %s""",
                           (amenity_name, amenity_description, amenity_id))
            conn.commit()
            conn.close()
            flash("Amenity updated successfully!")
            return redirect(url_for('view_amenities', property_id=amenity['property_id']))
        
        conn.close()
        return render_template('edit_amenity.html', amenity=amenity)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))    

# View Rooms Route
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
        flash("Unauthorized access.")
        return redirect(url_for('home'))
    
# Delete Room Route
@app.route('/delete_room/<int:room_id>', methods=['POST'])
def delete_room(room_id):
    """Allows admin to delete a room."""
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor()
        
        try:
            # Delete the room
            cursor.execute("DELETE FROM ROOMS WHERE room_id = %s", (room_id,))
            conn.commit()
            flash("Room deleted successfully!")
        except mysql.connector.Error as err:
            flash(f"Error deleting room: {err}")
        finally:
            conn.close()
        
        # Redirect back to the view_rooms page for the associated property
        return redirect(url_for('view_rooms', property_id=request.form['property_id']))
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))


# Add Room Route
@app.route('/add_room/<int:property_id>', methods=['GET', 'POST'])
def add_room(property_id):
    if 'logged_in' in session and session['role'] == 'admin':
        if request.method == 'POST':
            conn = create_connection()
            cursor = conn.cursor()
            room_type = request.form['room_type']
            capacity = request.form['capacity']
            price_per_night = request.form['price_per_night']
            availability_status = request.form.get('availability_status') == 'on'
            
            cursor.execute("""INSERT INTO ROOMS 
                              (property_id, room_type, capacity, price_per_night, availability_status)
                              VALUES (%s, %s, %s, %s, %s)""",
                           (property_id, room_type, capacity, price_per_night, availability_status))
            conn.commit()
            conn.close()
            flash("Room added successfully!")
            return redirect(url_for('view_rooms', property_id=property_id))
        
        return render_template('add_rooms.html', property_id=property_id)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))

# Edit Room Route
@app.route('/edit_room/<int:room_id>', methods=['GET', 'POST'])
def edit_room(room_id):
    if 'logged_in' in session and session['role'] == 'admin':
        conn = create_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch the room to be edited
        cursor.execute("SELECT * FROM ROOMS WHERE room_id = %s", (room_id,))
        room = cursor.fetchone()
        
        if request.method == 'POST':
            room_type = request.form['room_type']
            capacity = request.form['capacity']
            price_per_night = request.form['price_per_night']
            availability_status = request.form.get('availability_status') == 'on'
            
            cursor.execute("""UPDATE ROOMS SET room_type = %s, capacity = %s, 
                              price_per_night = %s, availability_status = %s
                              WHERE room_id = %s""",
                           (room_type, capacity, price_per_night, availability_status, room_id))
            conn.commit()
            conn.close()
            flash("Room updated successfully!")
            return redirect(url_for('view_rooms', property_id=room['property_id']))
        
        conn.close()
        return render_template('edit_rooms.html', room=room)
    else:
        flash("Unauthorized access.")
        return redirect(url_for('home'))
    


# Logout Route
@app.route('/logout')
def logout():
    """Logs the user out and clears the session."""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('home'))

@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    app.run(debug=True)