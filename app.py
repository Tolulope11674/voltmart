from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "voltMart-secret-key"

DATABASE = "store.db"


# -------------------------
# DATABASE CONNECTION
# -------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------
# CREATE DATABASE
# -------------------------
def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            image TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL NOT NULL,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Add sample products only if the table is empty
    count = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    if count == 0:
        products = [
            (
                "LED Bulb 12W",
                "Lighting",
                2500,
                "Energy-saving LED bulb suitable for homes and offices.",
                "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=500"
            ),
            (
                "Electrical Extension Box",
                "Accessories",
                7500,
                "Heavy-duty extension box with multiple sockets.",
                "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=500"
            ),
            (
                "Wall Light",
                "Lighting",
                12000,
                "Modern wall light for bedrooms, living rooms and offices.",
                "https://images.unsplash.com/photo-1524484485831-a92ffc0de03f?w=500"
            ),
            (
                "Circuit Breaker",
                "Protection",
                8500,
                "Reliable circuit breaker for electrical protection.",
                "https://images.unsplash.com/photo-1621905252507-b35492cc74b4?w=500"
            ),
            (
                "Electrical Switch",
                "Switches",
                3500,
                "Modern wall switch with a clean premium finish.",
                "https://images.unsplash.com/photo-1592833159155-c62df1b65634?w=500"
            ),
            (
                "Ceiling Fan",
                "Fans",
                65000,
                "Powerful and stylish ceiling fan for home and office.",
                "https://images.unsplash.com/photo-1626178793926-22b28830aa30?w=500"
            )
        ]

        conn.executemany("""
            INSERT INTO products
            (name, category, price, description, image)
            VALUES (?, ?, ?, ?, ?)
        """, products)

    conn.commit()
    conn.close()


# -------------------------
# HOME PAGE
# -------------------------
@app.route("/")
def home():
    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products LIMIT 6"
    ).fetchall()
    conn.close()

    return render_template("index.html", products=products)


# -------------------------
# PRODUCTS PAGE
# -------------------------
@app.route("/products")
def products():
    category = request.args.get("category")

    conn = get_db()

    if category:
        products = conn.execute(
            "SELECT * FROM products WHERE category = ?",
            (category,)
        ).fetchall()
    else:
        products = conn.execute(
            "SELECT * FROM products"
        ).fetchall()

    conn.close()

    return render_template(
        "products.html",
        products=products,
        selected_category=category
    )


# -------------------------
# REGISTER
# -------------------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO users (name, email, password)
                VALUES (?, ?, ?)
            """, (name, email, hashed_password))

            conn.commit()

            flash("Account created successfully. You can now login.", "success")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Email already exists.", "error")

        finally:
            conn.close()

    return render_template("register.html")


# -------------------------
# LOGIN
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            flash("Welcome back!", "success")

            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("home"))


# -------------------------
# CART
# -------------------------
@app.route("/cart")
def cart():

    cart = session.get("cart", [])

    conn = get_db()

    products = []

    total = 0

    for product_id in cart:

        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if product:
            products.append(product)
            total += product["price"]

    conn.close()

    return render_template(
        "cart.html",
        products=products,
        total=total
    )


# -------------------------
# ADD TO CART
# -------------------------
@app.route("/add_to_cart/<int:product_id>")
def add_to_cart(product_id):

    cart = session.get("cart", [])

    cart.append(product_id)

    session["cart"] = cart

    flash("Product added to cart.", "success")

    return redirect(request.referrer or url_for("products"))


# -------------------------
# REMOVE FROM CART
# -------------------------
@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):

    cart = session.get("cart", [])

    if product_id in cart:
        cart.remove(product_id)

    session["cart"] = cart

    return redirect(url_for("cart"))


# -------------------------
# CHECKOUT
# -------------------------
@app.route("/checkout", methods=["POST"])
def checkout():

    if "user_id" not in session:

        flash("Please login before checking out.", "error")

        return redirect(url_for("login"))

    cart = session.get("cart", [])

    if not cart:

        flash("Your cart is empty.", "error")

        return redirect(url_for("products"))

    conn = get_db()

    total = 0

    for product_id in cart:

        product = conn.execute(
            "SELECT price FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if product:
            total += product["price"]

    conn.execute("""
        INSERT INTO orders (user_id, total)
        VALUES (?, ?)
    """, (session["user_id"], total))

    conn.commit()
    conn.close()

    session["cart"] = []

    flash("Order placed successfully!", "success")

    return redirect(url_for("home"))


# -------------------------
# RUN APPLICATION
# -------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)