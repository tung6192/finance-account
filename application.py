from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from tempfile import gettempdir

from helpers import *

# configure application
app = Flask(__name__)

# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = gettempdir()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

@app.route("/")
@login_required
def index():
    users = db.execute("SELECT * FROM users WHERE id = :id", id = session["user_id"])
    stocks = db.execute("SELECT symbol, name, SUM(shares) as sum_of_shares, SUM(price) as sum_of_price, SUM(total) as sum_of_total\
                        FROM stocks WHERE user_id = :id\
                        GROUP BY user_id, symbol\
                        HAVING SUM(shares)>0",\
                        id = session["user_id"])
    
    # convert value to USD
    stock_value = 0
    for stock in stocks:
        stock_value += stock["sum_of_total"]
        stock["sum_of_price"] = usd(stock["sum_of_price"])
        stock["sum_of_total"] = usd(stock["sum_of_total"])
        
    # find total sum
    total_sum = users[0]["cash"]+stock_value
    
    # convert to usd
    users[0]["cash"] = usd(users[0]["cash"])
    total_sum = usd(total_sum)
    return render_template("index.html", user = users[0], stocks = stocks, total_sum = total_sum)

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""
    if request.method == "POST":
        
        # validate input
        stock = lookup(request.form["symbol"])
        if not stock:
            return apology("Invalid Symbol")
        try:
            shares = int(request.form["shares"])
        except ValueError:
            return apology("Invalid Shares")
        else:
            if shares <= 0:
                return apology("Requires positive integer")
        
        # compare current cash & spending
        user = db.execute("SELECT * FROM users WHERE id = :id", id = session["user_id"])
        cash = user[0]["cash"]
        if cash < shares*stock["price"]:
            return apology("Don't have enough cash")
        
        # insert to the stock table
        db.execute("INSERT INTO stocks(symbol, name, shares, price, total, user_id) VALUES(:symbol, :name, :shares, :price, :total, :user_id)",\
                    symbol = stock["symbol"], name = stock["name"], shares = shares, price = stock["price"], total = stock["price"]*shares, user_id = session["user_id"])
        db.execute("UPDATE users SET cash = :cash WHERE id = :id", cash = cash - stock["price"]*shares, id = session["user_id"])
        
        flash("You have just bought {} {} stocks".format(shares, stock["name"]))
        return redirect(url_for('index'))
    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    """Show history of transactions."""
    stocks = db.execute("SELECT * FROM stocks WHERE user_id = :id ORDER BY transacted DESC", id = session["user_id"])
    
    # convert value to USD
    for stock in stocks:
        stock["price"] = usd(stock["price"])
        stock["total"] = usd(stock["total"])
    return render_template("history.html", stocks = stocks)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username")

        # ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password")

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))

        # ensure username exists and password is correct
        if len(rows) != 1 or not pwd_context.verify(request.form.get("password"), rows[0]["hash"]):
            return apology("invalid username and/or password")

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user to home page
        return redirect(url_for("index"))

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("login"))

@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":
        stock = lookup(request.form["symbol"])
        if not stock:
            return apology("Invalid symbol")
        return render_template("quoted.html", stock = stock)
    else:
        return render_template("quote.html")
    
@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user."""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        repassword = request.form["repassword"]
        
        # request.form.get("username") == request.form["username"]
        if not username:
            return apology("missing username")
        if not password:
            return apology("missing password")
        if password != repassword:
            return apology("passwords do not match")
            
        # check existing user
        results = db.execute("SELECT * FROM users WHERE username = :username", username = username)
        if results:
            return apology("username already exists")
        db.execute("INSERT INTO users(username,hash) VALUES(:username, :hash)", username = username, hash = pwd_context.encrypt(password))
        
        # store user_id to session
        users = db.execute("SELECT * FROM users WHERE username = :username", username = username)
        session["user_id"] = users[0]["id"]
        
        flash("You are successfully registered")
        return redirect(url_for('index'))
    else:
        return render_template("register.html")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""
    if request.method == "POST":
        
        # validate symbol
        stock = lookup(request.form["symbol"])
        if not stock:
            return apology("Invalid Symbol")

        rows = db.execute("SELECT symbol, name, SUM(shares) as sum_of_shares, SUM(price) as sum_of_price, SUM(total) as sum_of_total\
                        FROM stocks WHERE user_id = :id AND symbol= :symbol\
                        GROUP BY user_id, symbol\
                        HAVING SUM(shares)>0",\
                        id = session["user_id"], symbol = stock["symbol"])
        if not rows or rows[0]["sum_of_shares"]==0:
            return apology("You don't own any {}".format(stock["name"]))
            
        # validate shares
        try:
            shares = int(request.form["shares"])
        except ValueError:
            return apology("Invalid Shares")
        else:
            if shares <= 0:
                return apology("Requires positive integer")
        
        if rows[0]["sum_of_shares"]<shares:
            return apology("You don't have enough {} stocks to sell".format(stock["name"]))
        else:
            db.execute("INSERT INTO stocks(symbol, name, shares, price, total, user_id) VALUES(:symbol, :name, :shares, :price, :total, :user_id)",\
                        symbol = stock["symbol"], name = stock["name"], shares = -shares, price = stock["price"], total = stock["price"]*shares, user_id = session["user_id"])
            
            users = db.execute("SELECT * FROM users where id =:id", id = session["user_id"])
            db.execute("UPDATE users SET cash = :cash WHERE id = :id", cash = users[0]["cash"] + stock["price"]*shares, id = session["user_id"])
        
        flash("You have just sold {} {} stocks".format(shares, stock["name"]))
        return redirect(url_for('index'))
    else:
        return render_template("sell.html")

@app.route("/add_cash", methods=["GET", "POST"])
@login_required
def add_cash():
    if request.method == "POST":
        
        # validate amount of money
        try:
            amount = int(request.form["cash"])
            print(request.form["cash"])
        except ValueError:
            return apology("Invalid Amount of Money")
        else:
            if amount <= 0:
                return apology("Requires positive integer")
        
        users = db.execute("SELECT * FROM users WHERE id = :id", id = session["user_id"])
        db.execute("UPDATE users SET cash = :cash WHERE id = :id", cash = users[0]["cash"] + amount, id = session["user_id"])
        
        flash("You have just successfully added ${} to your account".format(amount))
        return redirect(url_for('index'))
    else:
        users = db.execute("SELECT * FROM users WHERE id = :id", id = session["user_id"])
        return render_template("add_cash.html", cash = usd(users[0]["cash"]))