
import sqlite3
import os
import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError

# Load .env from the same folder as app.py
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("voltmart")

app = FastAPI(title="VoltMart")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "FLASK_SECRET_KEY",
        "dev-only-change-this-key"
    )
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")

DATABASE = str(BASE_DIR / "store.db")

# -------------------------
# AI CLIENT
# -------------------------
# Create the AI client only when a key is configured
api_key = os.getenv("OPENAI_API_KEY", "").strip()

client = OpenAI(api_key=api_key) if api_key else None


# -------------------------
# TEMPLATE HELPERS
# -------------------------
# The templates were written for Flask, so these helpers give them the
# same url_for, session and get_flashed_messages they already use.
@pass_context
def url_for(context, name, **params):
    request = context["request"]

    if name == "static":
        return str(request.url_for("static", path=params.pop("filename")))

    route = next(
        r for r in request.app.routes if getattr(r, "name", None) == name
    )
    path_params = {
        key: params.pop(key) for key in list(params)
        if key in route.param_convertors
    }

    url = str(request.url_for(name, **path_params))

    if params:
        url += "?" + urlencode(params)

    return url


@pass_context
def get_flashed_messages(context, with_categories=False):
    messages = context["request"].session.pop("_flashes", [])

    if with_categories:
        return [tuple(message) for message in messages]

    return [message for _, message in messages]


templates.env.globals["url_for"] = url_for
templates.env.globals["get_flashed_messages"] = get_flashed_messages


def flash(request, message, category="message"):
    flashes = request.session.get("_flashes", [])
    flashes.append([category, message])
    request.session["_flashes"] = flashes


def render(request, template, **context):
    return templates.TemplateResponse(
        request,
        template,
        {
            "session": request.session,
            "cart_count": len(request.session.get("cart", [])),
            **context
        }
    )


def redirect(url):
    return RedirectResponse(url, status_code=303)


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
@app.get("/", response_class=HTMLResponse, name="home")
def home(request: Request):
    conn = get_db()

    products = conn.execute(
        "SELECT * FROM products LIMIT 6"
    ).fetchall()

    conn.close()

    return render(request, "index.html", products=products)


# -------------------------
# PRODUCTS PAGE
# -------------------------
@app.get("/products", response_class=HTMLResponse, name="products")
def products(request: Request, category: str | None = None):
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

    return render(
        request,
        "products.html",
        products=products,
        selected_category=category
    )


# -------------------------
# REGISTER
# -------------------------
@app.get("/register", response_class=HTMLResponse, name="register")
def register_page(request: Request):
    return render(request, "register.html")


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    hashed_password = generate_password_hash(password)

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO users (name, email, password)
            VALUES (?, ?, ?)
        """, (name, email, hashed_password))

        conn.commit()

        flash(
            request,
            "Account created successfully. You can now login.",
            "success"
        )

        return redirect(request.url_for("login"))

    except sqlite3.IntegrityError:
        flash(request, "Email already exists.", "error")

    finally:
        conn.close()

    return render(request, "register.html")


# -------------------------
# LOGIN
# -------------------------
@app.get("/login", response_class=HTMLResponse, name="login")
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    conn.close()

    if user and check_password_hash(user["password"], password):
        request.session["user_id"] = user["id"]
        request.session["user_name"] = user["name"]

        flash(request, "Welcome back!", "success")

        return redirect(request.url_for("home"))

    flash(request, "Invalid email or password.", "error")

    return render(request, "login.html")


# -------------------------
# LOGOUT
# -------------------------
@app.get("/logout", name="logout")
def logout(request: Request):
    request.session.clear()

    flash(request, "You have been logged out.", "success")

    return redirect(request.url_for("home"))


# -------------------------
# CART
# -------------------------
@app.get("/cart", response_class=HTMLResponse, name="cart")
def cart(request: Request):
    cart_items = request.session.get("cart", [])

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

    return render(
        request,
        "cart.html",
        products=products,
        total=total
    )


# -------------------------
# ADD TO CART
# -------------------------
@app.get("/add_to_cart/{product_id}", name="add_to_cart")
def add_to_cart(request: Request, product_id: int):
    conn = get_db()

    product = conn.execute(
        "SELECT id FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    conn.close()

    if not product:
        flash(request, "Product not found.", "error")
        return redirect(request.url_for("products"))

    cart_items = request.session.get("cart", [])
    cart_items.append(product_id)
    request.session["cart"] = cart_items

    flash(request, "Product added to cart.", "success")

    return redirect(
        request.headers.get("referer") or request.url_for("products")
    )


# -------------------------
# REMOVE FROM CART
# -------------------------
@app.get("/remove_from_cart/{product_id}", name="remove_from_cart")
def remove_from_cart(request: Request, product_id: int):
    cart_items = request.session.get("cart", [])

    if product_id in cart_items:
        cart_items.remove(product_id)

    request.session["cart"] = cart_items

    return redirect(request.url_for("cart"))


# -------------------------
# CHECKOUT
# -------------------------
@app.post("/checkout", name="checkout")
def checkout(request: Request):
    if "user_id" not in request.session:
        flash(request, "Please login before checking out.", "error")
        return redirect(request.url_for("login"))

    cart_items = request.session.get("cart", [])

    if not cart_items:
        flash(request, "Your cart is empty.", "error")
        return redirect(request.url_for("products"))

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
        """, (request.session["user_id"], total))

        conn.commit()

    finally:
        conn.close()

    request.session["cart"] = []

    flash(request, "Order placed successfully!", "success")

    return redirect(request.url_for("home"))


# -------------------------
# AI SHOPPING ASSISTANT
# -------------------------
def error(message, status_code):
    return JSONResponse({"error": message}, status_code=status_code)


@app.post("/ai-chat", name="ai_chat")
async def ai_chat(request: Request):
    if client is None:
        logger.error("OPENAI_API_KEY is missing.")
        return error(
            "The AI API key is missing. Check your .env file.", 503
        )

    try:
        data = await request.json()
    except ValueError:
        data = None

    if not isinstance(data, dict):
        data = {}

    question = data.get("message", "")

    if not isinstance(question, str) or not question.strip():
        return error("Please enter a message.", 400)

    question = question.strip()

    if len(question) > 1000:
        return error("Your message must be under 1000 characters.", 400)

    try:
        response = await run_in_threadpool(
            client.responses.create,
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
            return error(
                "The AI returned an empty answer. Please try again.", 502
            )

        return {"reply": answer}

    except AuthenticationError:
        logger.error(
            "OpenAI authentication failed. Check OPENAI_API_KEY in .env."
        )
        return error(
            "The AI API key is invalid. Check your .env configuration.", 401
        )

    except RateLimitError:
        logger.exception("OpenAI API quota or rate limit error.")
        return error(
            "The AI service has a usage limit or quota issue.", 429
        )

    except APIConnectionError:
        logger.exception("Could not connect to the OpenAI API.")
        return error(
            "Could not connect to the AI service. Please try again.", 502
        )

    except Exception:
        logger.exception("VoltMart AI request failed.")
        return error(
            "The AI service encountered an error. Please try again.", 500
        )


# -------------------------
# CUSTOMER SERVICE PAGE
# -------------------------
@app.get(
    "/customer-service",
    response_class=HTMLResponse,
    name="customer_service"
)
def customer_service(request: Request):
    return render(request, "chat-box-ai.html")


# -------------------------
# INITIALIZE DATABASE
# -------------------------
init_db()


# -------------------------
# RUN APPLICATION
# -------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", reload=True)
