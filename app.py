
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
import sqlite3
import os
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError

# Load .env from the same folder as app.py
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

@app.context_processor
def cart_count():
    cart = session.get("cart", [])
    return {"cart_count": len(cart)}

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "dev-only-change-this-key"
)

DATABASE = str(BASE_DIR / "store.db")

# Create the AI client only when a key is configured
api_key = os.getenv("OPENAI_API_KEY", "").strip()

client = OpenAI(api_key=api_key) if api_key else None

# -------------------------
# AI CLIENT
# -------------------------
client = (
    OpenAI()
    if os.getenv("OPENAI_API_KEY")
    else None
)


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

            flash(
                "Account created successfully. You can now login.",
                "success"
            )

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
    cart_items = session.get("cart", [])

    conn = get_db()

    products = []
    total = 0

    for product_id in cart_items:
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
    conn = get_db()

    product = conn.execute(
        "SELECT id FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    conn.close()

    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("products"))

    cart_items = session.get("cart", [])
    cart_items.append(product_id)
    session["cart"] = cart_items

    flash("Product added to cart.", "success")

    return redirect(request.referrer or url_for("products"))


# -------------------------
# REMOVE FROM CART
# -------------------------
@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):
    cart_items = session.get("cart", [])

    if product_id in cart_items:
        cart_items.remove(product_id)

    session["cart"] = cart_items

    return redirect(url_for("cart"))


# -------------------------
# CHECKOUT
# -------------------------
@app.route("/checkout", methods=["POST"])
def checkout():
    if "user_id" not in session:
        flash("Please login before checking out.", "error")
        return redirect(url_for("login"))

    cart_items = session.get("cart", [])

    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("products"))

    conn = get_db()

    try:
        total = 0

        for product_id in cart_items:
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

    finally:
        conn.close()

    session["cart"] = []

    flash("Order placed successfully!", "success")

    return redirect(url_for("home"))


# -------------------------
# AI SHOPPING ASSISTANT
# -------------------------

@app.route("/ai-chat", methods=["POST"])
def ai_chat():
    if client is None:
        app.logger.error("OPENAI_API_KEY is missing.")
        return jsonify({
            "error": "The AI API key is missing. Check your .env file."
        }), 503

    data = request.get_json(silent=True) or {}
    question = data.get("message", "")

    if not isinstance(question, str) or not question.strip():
        return jsonify({
            "error": "Please enter a message."
        }), 400

    question = question.strip()

    if len(question) > 1000:
        return jsonify({
            "error": "Your message must be under 1000 characters."
        }), 400

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=(
                "You are VoltMart's friendly customer-care assistant. "
                "Help customers with electrical products and shopping. "
                "Be clear, polite, and helpful. Do not invent prices, "
                "stock levels, or order details. Recommend a qualified "
                "electrician for electrical installation or repair work."
            ),
            input=question
        )

        answer = response.output_text

        if not answer:
            return jsonify({
                "error": "The AI returned an empty answer. Please try again."
            }), 502

        return jsonify({"reply": answer})

    except AuthenticationError:
        app.logger.error(
            "OpenAI authentication failed. Check OPENAI_API_KEY in .env."
        )
        return jsonify({
            "error": "The AI API key is invalid. Check your .env configuration."
        }), 401

    except RateLimitError:
        app.logger.exception("OpenAI API quota or rate limit error.")
        return jsonify({
            "error": "The AI service has a usage limit or quota issue."
        }), 429

    except APIConnectionError:
        app.logger.exception("Could not connect to the OpenAI API.")
        return jsonify({
            "error": "Could not connect to the AI service. Please try again."
        }), 502

    except Exception:
        app.logger.exception("VoltMart AI request failed.")
        return jsonify({
            "error": "The AI service encountered an error. Please try again."
        }), 500

# -------------------------
# INITIALIZE DATABASE
# -------------------------
init_db()


# -------------------------
# CUSTOMER SERVICE PAGE
# -------------------------
@app.route("/customer-service")
def customer_service():
    return render_template("chat-box-ai.html")

# -------------------------
# RUN APPLICATION
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)