Commands to run: 
Command prompt:
start-dfs.cmd
start-yarn.cmd
jps

VS code ot Terminal
python app.py

# StayNGo

StayNGo is a web-based platform designed to address the challenges faced by middle-class and lower-income individuals in accessing affordable temporary lodging, especially when seeking medical care in distant cities. Inspired by the long waiting periods at renowned hospitals like Tata, StayNGo aims to provide a centralized solution for finding budget-friendly accommodations near essential services.

<img width="975" height="477" alt="image" src="https://github.com/user-attachments/assets/b1cab99c-68df-42ff-8142-032ac3c58ff2" />

---

## The Problem

Many patients and their families travel significant distances to access quality healthcare. During the often lengthy waiting periods (5-7 days or more) for medical appointments or procedures, they require temporary lodging. However, conventional options like OYO or Trivago are often prohibitively expensive, adding a substantial financial burden to already vulnerable individuals.

---

## Our Solution: StayNGo

StayNGo leverages a robust **Database Management System (DBMS)** to connect users with affordable rental rooms. Our platform focuses on:

- **Affordability:** Providing cost-effective alternatives to traditional hotels.
- **Proximity:** Helping users find lodging close to hospitals and other critical locations.
- **Ease of Use:** Simplifying the search and booking process through efficient data management.

---

## Key Features

### Data Filtering and Querying

Our database stores comprehensive information on rental properties, including:

- **Location:** Precise addresses and proximity to key landmarks like hospitals.
- **Pricing:** Transparent and affordable rates.
- **Amenities:** Details about available facilities (e.g., kitchen, Wi-Fi, laundry).

Users can quickly **filter accommodations** based on their budget, desired distance from medical centers, or specific amenity requirements, making the search process efficient and tailored to their needs.

### Side-by-Side Comparisons

StayNGo enables users to **compare different rental options** directly within the platform. This feature highlights crucial factors such as cost, amenities, and location, empowering users to make informed decisions without the need to visit multiple websites or physical locations.

### Reporting and Analytics

We utilize data analytics to gain insights into user preferences and booking trends. This allows us to:

- **Optimize Offerings:** Continuously improve the selection of available accommodations.
- **Identify High-Demand Periods:** Understand peak booking times to better serve users.
- **Provide Better Recommendations:** Offer personalized suggestions based on past behavior and preferences.

For property owners, our analytics provide valuable insights into demand trends, enabling them to adjust pricing strategies and enhance their services.

### Scalability

StayNGo is built with **scalability** in mind. The platform can efficiently handle increasing data volumes and readily expand its coverage to include more rental options and new geographical areas. This ensures that StayNGo can adapt to growth and continue to serve a growing user base, including patients, their families, and even students seeking affordable housing.

---

## Technology Stack

- **Frontend:** HTML templates rendered by Flask
- **Backend:** Flask (Python)
- **Database:** MySQL

---

## For Runnig the frontend

1)pip install -r requirements.txt (Windows/Linux) or pip3 install -r requirements.txt(MacOS)
2)python app.py (Windows/Linux) or python3 app.py (MacOs)

## Database Schema

The StayNGo database is structured to efficiently manage information related to users, properties, rooms, amenities, bookings, payments, and reviews.

```sql
-- Create USERS table
CREATE TABLE USERS (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') NOT NULL,
    phone_number VARCHAR(15),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Create PROPERTIES table
CREATE TABLE PROPERTIES (
    property_id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    address VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    description TEXT,
    image_url VARCHAR(500),
    image_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES USERS(user_id) ON DELETE CASCADE
);

-- Create ROOMS table
CREATE TABLE ROOMS (
    room_id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    room_type VARCHAR(50) NOT NULL,
    capacity INT NOT NULL,
    price_per_night DECIMAL(10, 2) NOT NULL,
    availability_status BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (property_id) REFERENCES PROPERTIES(property_id) ON DELETE CASCADE
);

-- Create AMENITIES table
CREATE TABLE AMENITIES (
    amenity_id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (property_id) REFERENCES PROPERTIES(property_id) ON DELETE CASCADE
);

-- Create BOOKINGS table
CREATE TABLE BOOKINGS (
    booking_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    room_id INT NOT NULL,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    total_price DECIMAL(10, 2) NOT NULL,
    booking_status ENUM('confirmed', 'cancelled', 'completed') DEFAULT 'confirmed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE,
    FOREIGN KEY (room_id) REFERENCES ROOMS(room_id) ON DELETE CASCADE
);

-- Create PAYMENTS table
CREATE TABLE PAYMENTS (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    payment_status ENUM('pending', 'completed', 'failed', 'refunded') DEFAULT 'pending',
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES BOOKINGS(booking_id) ON DELETE CASCADE
);

-- Create REVIEWS table
CREATE TABLE REVIEWS (
    review_id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    user_id INT NOT NULL,
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES ROOMS(room_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE
);
```
