from fasthtml.common import *
from rich.console import Console
from rich import print
from rich.traceback import install
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List
import json

# Enable Rich traceback for debugging
install()
console = Console()

# Paths configuration
SCRIPT_PATH = Path(__file__).resolve()
BASE_PATH = SCRIPT_PATH.parent.parent
DATA_PATH = BASE_PATH / 'data'
STATIC_PATH = SCRIPT_PATH.parent / 'static'
DATABASE = DATA_PATH / 'shopping_list.db'

# Create custom stylesheet link for our CSS
custom_styles = Link(
    rel="stylesheet",
    href="/static/css/style.css",
    type="text/css"
)

# Initialize FastHTML app with styling
app = FastHTML(hdrs=(picolink, custom_styles))

# Serve static files
@app.get("/static/{path:path}")
def static_files(path: str):
    """Serve static files from the static directory."""
    return FileResponse(STATIC_PATH / path)
class ShoppingItem(BaseModel):
    id: Optional[int] = None
    category: str
    item: str
    quantity: int = Field(ge=0)
    cost: float = Field(ge=0)
    notes: Optional[str] = None
    found: bool = False
    store: str

    @field_validator('cost')
    @classmethod
    def validate_cost(cls, v: float) -> float:
        return round(float(v), 2)

class BudgetUpdate(BaseModel):
    amount: float = Field(ge=0)

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: float) -> float:
        return round(float(v), 2)
class DatabaseError(Exception):
    """Custom exception for database operations."""
    pass

def setup_database():
    """Initialize database with improved schema."""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        # Drop existing tables to ensure clean slate
        c.execute("DROP TABLE IF EXISTS shopping_list")
        c.execute("DROP TABLE IF EXISTS budget")
        
        # Create tables with proper constraints
        c.execute("""CREATE TABLE shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            item TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity >= 0),
            cost REAL NOT NULL CHECK (cost >= 0),
            notes TEXT,
            found INTEGER DEFAULT 0,
            store TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK (amount >= 0)
        )""")

        # Create indices for better query performance
        c.execute("CREATE INDEX IF NOT EXISTS idx_category ON shopping_list(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_found ON shopping_list(found)")
        
        # Set initial budget
        c.execute("INSERT INTO budget (amount) VALUES (?)", (1000.00,))

        conn.commit()
        conn.close()
        console.log("Database setup successful", style="bold green")
    except sqlite3.Error as e:
        console.log(f"Database error: {e}", style="bold red")
        raise DatabaseError(f"Failed to setup database: {e}")

def get_db_connection():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_budget() -> float:
    """Get current budget amount."""
    try:
        with get_db_connection() as conn:
            result = conn.execute(
                "SELECT amount FROM budget ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return float(result['amount']) if result else 0.0
    except sqlite3.Error as e:
        console.log(f"Error getting budget: {e}", style="bold red")
        return 0.0

def get_total_cost() -> float:
    """Calculate total cost of all items."""
    try:
        with get_db_connection() as conn:
            result = conn.execute(
                "SELECT SUM(cost * quantity) as total FROM shopping_list"
            ).fetchone()
            return float(result['total']) if result['total'] else 0.0
    except sqlite3.Error as e:
        console.log(f"Error calculating total cost: {e}", style="bold red")
        return 0.0

def fetch_shopping_list() -> Dict[str, List[dict]]:
    """Fetch items sorted by found status and grouped by category."""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM shopping_list 
                ORDER BY found ASC, category ASC, id DESC
            """)
            items = [dict(row) for row in cursor.fetchall()]
            
            # Group items by category
            categories = {}
            for item in items:
                if item['category'] not in categories:
                    categories[item['category']] = []
                categories[item['category']].append(item)
            
            return categories
    except sqlite3.Error as e:
        console.log(f"Error fetching shopping list: {e}", style="bold red")
        return {}

def add_item(category: str, item: str, quantity: int, cost: float, notes: str, store: str):
    """Add new item with validation."""
    try:
        if quantity < 0:
            return Div("Quantity cannot be negative", cls="error-message")
        if cost < 0:
            return Div("Cost cannot be negative", cls="error-message")
            
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO shopping_list 
                (category, item, quantity, cost, notes, store)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (category, item, quantity, cost, notes, store))
            conn.commit()
            
        return ShoppingTable(fetch_shopping_list())
    except sqlite3.Error as e:
        console.log(f"Error adding item: {e}", style="bold red")
        return Div("Failed to add item", cls="error-message")

def make_editable_cell(item_id: str|int, value: str, field: str, cls: str = "") -> Div:
    """Create an editable cell with improved hover effects.
    
    Args:
        item_id: Identifier for the item
        value: Value to display
        field: Field name to edit
        cls: Additional CSS classes (optional)
    """
    return Div(
        str(value),
        hx_get=f"/edit/{item_id}/{field}",
        hx_trigger="click",
        hx_target="this",
        hx_swap="outerHTML",
        cls=f"editable-cell {cls}".strip()
    )

def BudgetStatus():
    """Enhanced budget status component with inline editing."""
    budget = get_budget()
    total_cost = get_total_cost()
    remaining = budget - total_cost
    status = "success" if remaining >= 0 else "error"
    
    return Article(
        Div(
            H3("Budget Status", cls="budget-title"),
            Div(
                Div(
                    H4("Total Budget", cls="budget-label"),
                    make_editable_cell("budget", f"${budget:.2f}", "amount", "budget-value"),
                ),
                Div(
                    H4("Total Cost", cls="budget-label"),
                    P(f"${total_cost:.2f}", cls="budget-value")
                ),
                Div(
                    H4("Remaining", cls="budget-label"),
                    P(f"${remaining:.2f}", cls=f"budget-value text-{status}")
                ),
                cls="budget-grid"
            ),
            id="budget-status",
            cls="budget-card"
        )
    )

def ShoppingContainer(categories: Dict[str, List[dict]]) -> Div:
    """Container for shopping list."""
    return Div(
        Div(  # Wrapper for the table to control margin
            ShoppingTable(categories),
            cls="shopping-table-wrapper"
        ),
        id="shopping-container"
    )
def NewItemForm() -> Form:
    """Grid-based form for adding new items with mobile-friendly layout."""
    return Form(
        H3("Add New Item", cls="form-title"),
        Div(
            Div(
                Input(
                    name="category",
                    placeholder="Category",
                    required=True,
                    cls="form-input"
                ),
                Input(
                    name="item",
                    placeholder="Item",
                    required=True,
                    cls="form-input"
                ),
                cls="form-row"
            ),
            Div(
                Input(
                    name="quantity",
                    type="number",
                    min="0",
                    required=True,
                    placeholder="Quantity",
                    cls="form-input"
                ),
                Input(
                    name="cost",
                    type="number",
                    step="0.01",
                    min="0",
                    required=True,
                    placeholder="Cost",
                    cls="form-input"
                ),
                cls="form-row"
            ),
            Input(
                name="store",
                placeholder="Store",
                required=True,
                cls="form-input"
            ),
            Textarea(
                name="notes",
                placeholder="Notes",
                cls="form-input"
            ),
            Button(
                "Add Item",
                type="submit",
                cls="button-primary"
            ),
            cls="grid-form"
        ),
        action="/add_item",
        method="post",
        hx_target="#shopping-container",
        hx_swap="innerHTML"
    )

def ShoppingTable(categories: Dict[str, List[dict]]) -> Div:
    """Generate responsive shopping table grouped by category."""
    if not categories:
        return Div(P("No items yet!", cls="text-center"), cls="empty-state")
    
    mobile_cards = []
    for category, items in sorted(categories.items()):
        sorted_items = sorted(items, key=lambda x: (x['found'], -x['id']))
        
        category_items = []
        for item in sorted_items:
            category_items.append(
                Div(
                    Div(
                        Input(
                            type="checkbox",
                            checked=bool(item['found']),
                            hx_post=f"/toggle_found/{item['id']}",
                            hx_target="#shopping-container",
                            hx_swap="innerHTML"
                        ),
                        H4(item['item']),
                        cls="card-header"
                    ),
                    Div(
                        P(f"Quantity: {item['quantity']}"),
                        P(f"Cost: ${item['cost']:.2f}"),
                        P(f"Store: {item['store']}"),
                        P(f"Notes: {item['notes'] or '-'}"),
                        Button(
                            "Remove",
                            hx_post=f"/remove_item/{item['id']}",
                            hx_target="#shopping-container",
                            hx_swap="innerHTML",
                            cls="button-error mt-2"
                        ),
                        cls="card-body"
                    ),
                    cls=f"item-card {item['found'] and 'found-item'}"
                )
            )
        
        mobile_cards.append(
            Div(
                H3(category, cls="category-title"),
                *category_items,
                cls="category-section"
            )
        )
    
    return Div(*mobile_cards, cls="shopping-list")
    
add_new_item_button = Button(
    "Add New Item",
    hx_get="/new_item_form",
    hx_swap="outerHTML",
    hx_target="#modal",
    cls="button-primary full-width mb-4"  # Utility class for margin-bottom
)
@app.get("/")
def home():
    categories = fetch_shopping_list()
    return (
        Title("House Painting Shopping List"),
        Meta(name="viewport", content="width=device-width, initial-scale=1.0, viewport-fit=cover"),
        Main(
            Div(
                BudgetStatus(),
                add_new_item_button ,
                ShoppingContainer(categories),
                Div(cls="spacer", style="height: 1.5rem;"),
                Div(id="modal"),  # Modal container (empty by default)
                id="content-container",  # Wrap the full content for updates
                cls="container"
            )
        )
    )

@app.get("/new_item_form")
def new_item_form():
    """Return the form for adding a new item inside a modal."""
    return Div(
        Div(
            Div(
                H3("Add New Item"),
                Button(
                    "×",  # Text for the button
                    hx_get="/close_modal",  # HTMX attribute to call the /close_modal endpoint
                    hx_target="#modal",     # Target the modal container
                    hx_swap="outerHTML",    # Replace the entire modal content
                    cls="modal-close",      # CSS class for styling
                    _="on click htmx.ajax('GET', '/close_modal', {target: '#modal'})"  # Optional for additional JS behavior
                ),
                cls="modal-header"
            ),
            Form(
                Div(
                    Input(name="category", placeholder="Category", required=True),
                    Input(name="item", placeholder="Item", required=True),
                    Div(
                        Input(name="quantity", type="number", min="0", placeholder="Quantity", required=True),
                        Input(name="cost", type="number", step="0.01", min="0", placeholder="Cost", required=True),
                        cls="form-row"
                    ),
                    Input(name="store", placeholder="Store", required=True),
                    Textarea(name="notes", placeholder="Notes"),
                    Button("Add Item", type="submit", cls="button-primary"),
                    cls="modal-form"
                ),
                action="/add_item",
                method="post",
                hx_target="#shopping-container",  # Updates shopping container
                hx_swap="innerHTML",
                _="on submit target.reset() then htmx.ajax('GET', '/close_modal', {target: '#modal'})"
            ),
            cls="modal-content"
        ),
        id="modal",
        cls="modal show"  # Makes the modal visible
    )
@app.get("/close_modal")
def close_modal():
    """Close and reset the modal."""
    return Div(id="modal", cls="modal hidden")  # Clear modal content and hide

@app.post("/add_item")
def add_item(item: ShoppingItem):
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO shopping_list 
                (category, item, quantity, cost, notes, store)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (item.category, item.item, item.quantity, item.cost, 
                  item.notes, item.store))
            conn.commit()
        
        # Return updated shopping list and reset modal
        return [
            ShoppingContainer(fetch_shopping_list()),
            Div(id="modal")  # Reset modal to an empty state
        ]
    except sqlite3.Error as e:
        console.log(f"Error adding item: {e}", style="bold red")
        return Div("Failed to add item", cls="error-message", id="form-errors")
@app.get("/edit/budget/amount")
def edit_budget_form():
    """Return an inline editable form for the budget."""
    budget = get_budget()

    return Form(
        Input(
            type="number",
            name="value",
            value=f"{budget:.2f}",
            step="0.01",
            min="0",
            cls="edit-input",
            _autofocus=True
        ),
        Button("Save", type="submit", cls="button-primary"),
        hx_post="/update/budget/amount",
        hx_target="#content-container",  # Target the entire content container
        hx_swap="outerHTML"  # Replace the full container
    )

@app.post("/update/budget/amount")
def update_budget_inline(value: str):
    """Update budget with validation and replace the full container."""
    try:
        # Parse and validate the budget amount
        budget = float(value.replace("$", "").strip())
        if budget < 0:
            return Div("Budget cannot be negative", cls="error-message")

        # Update the budget in the database
        with get_db_connection() as conn:
            conn.execute("INSERT INTO budget (amount) VALUES (?)", (budget,))
            conn.commit()

        # Fetch updated categories for the shopping list
        categories = fetch_shopping_list()

        # Return the full updated content: BudgetStatus + ShoppingContainer
        return Div(
                BudgetStatus(),
                add_new_item_button ,
                ShoppingContainer(categories),
                Div(cls="spacer", style="height: 1.5rem;"),
                Div(id="modal"),  # Modal container (empty by default)
                id="content-container",  # Wrap the full content for updates
                cls="container"
            )
        
    except ValueError:
        # Handle invalid input
        return Div("Invalid budget amount. Please enter a valid number.", cls="error-message")
    except sqlite3.Error as e:
        # Handle database errors
        console.log(f"Error updating budget: {e}", style="bold red")
        return Div("Failed to update the budget due to a database error.", cls="error-message")
@app.post("/set_budget")
def update_budget(budget: float):
    """Update budget with validation."""
    try:
        if budget < 0:
            return Div("Budget cannot be negative", cls="error-message")
            
        with get_db_connection() as conn:
            conn.execute("INSERT INTO budget (amount) VALUES (?)", (budget,))
            conn.commit()
            
        # Return the full shopping container to update both budget and list
        return ShoppingContainer(fetch_shopping_list())
    except sqlite3.Error as e:
        console.log(f"Error updating budget: {e}", style="bold red")
        return Div("Failed to update budget", cls="error-message")


@app.post("/toggle_found/{item_id}")
def toggle_found(item_id: int):
    """Toggle found status of an item."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE shopping_list SET found = NOT found WHERE id = ?",
                (item_id,)
            )
            conn.commit()
            
        return ShoppingContainer(fetch_shopping_list())
    except sqlite3.Error as e:
        console.log(f"Error toggling found status: {e}", style="bold red")
        return Div("Failed to update item status", cls="error-message")

@app.post("/remove_item/{item_id}")
def remove_item(item_id: int):
    """Remove an item from the list."""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
            conn.commit()
            
        return ShoppingContainer(fetch_shopping_list())
    except sqlite3.Error as e:
        console.log(f"Error removing item: {e}", style="bold red")
        return Div("Failed to remove item", cls="error-message")

@app.get("/edit/{item_id}/{field}")
def edit_form(item_id: int, field: str):
    """Return an edit form for the specified field."""
    input_type = "number" if field in ["quantity", "cost"] else "text"
    step = "0.01" if field == "cost" else "1" if field == "quantity" else None
    min_value = "0" if field in ["quantity", "cost"] else None
    
    try:
        with get_db_connection() as conn:
            result = conn.execute(
                f"SELECT {field} FROM shopping_list WHERE id = ?",
                (item_id,)
            ).fetchone()
            
            if not result:
                return Div("Item not found", cls="error-message")
            
            value = result[field]
            if field == "cost" and isinstance(value, str) and value.startswith("$"):
                value = value[1:]

            return Form(
                Input(
                    type=input_type,
                    name="value",
                    value=value,
                    step=step,
                    min=min_value,
                    cls="edit-input",
                    _autofocus=True
                ),
                Button("Save", type="submit"),
                hx_post=f"/update/{item_id}/{field}",
                hx_target="closest td",
                _="on blur from .edit-input trigger submit"
            )
    except sqlite3.Error as e:
        console.log(f"Error creating edit form: {e}", style="bold red")
        return Div("Error loading edit form", cls="error-message")

@app.post("/update/{item_id}/{field}")
def update_field(item_id: int, field: str, value: str):
    """Update a single field with validation."""
    try:
        # Input validation
        if not value.strip():
            return Div(f"{field.title()} cannot be empty", cls="error-message")
        
        # Handle numeric fields
        if field in ["quantity", "cost"]:
            try:
                if field == "cost":
                    value = float(value.replace("$", "").strip())
                else:
                    value = int(value)
                
                if value < 0:
                    return Div(f"{field.title()} cannot be negative", cls="error-message")
            except ValueError:
                return Div(f"Invalid {field} format", cls="error-message")
        
        # Update database
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE shopping_list SET {field} = ? WHERE id = ?",
                (value, item_id)
            )
            conn.commit()
            
            # Return full container to update totals
            return ShoppingContainer(fetch_shopping_list())
            
    except sqlite3.Error as e:
        console.log(f"Error updating field: {e}", style="bold red")
        return Div("Failed to update value", cls="error-message")
def populate_sample_data():
    """Populate the database with all painting supplies using correct store information."""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()

        # Complete list of items with correct stores and prices
        items = [
            # Spray Equipment
            ("Spray Equipment", "Paint sprayer (airless)", 1, 40.00, "Consider renting if one-time use, rental price per day", 0, "Home Depot"),
            ("Spray Equipment", "Spray tips", 3, 20.00, "Different sizes for walls vs. trim", 0, "Home Depot"),
            ("Spray Equipment", "Extension wand", 1, 30.00, "For reaching high areas", 0, "Home Depot"),
            ("Spray Equipment", "Filters", 6, 5.00, "Replace as needed", 0, "Home Depot"),
            ("Spray Equipment", "Hose", 1, 25.00, "Usually comes with sprayer", 0, "Home Depot"),

            # Paint
            ("Paint", "Interior latex paint", 10, 37.50, "Account for overspray, $25-$50/gal", 0, "Lowe's"),
            ("Paint", "Primer", 8, 30.00, "If needed, $20-$40/gal", 0, "Lowe's"),
            ("Paint", "Paint strainer", 6, 2.00, "To prevent sprayer clogs", 0, "Lowe's"),

            # Protection
            ("Protection", "Plastic sheeting", 5, 10.00, "Cover EVERYTHING", 0, "Walmart"),
            ("Protection", "Painter's tape", 10, 5.00, "More needed for spray painting", 0, "Walmart"),
            ("Protection", "Rosin paper", 3, 15.00, "Floor protection", 0, "Home Depot"),
            ("Protection", "Drop cloths", 6, 15.00, "Heavy-duty type", 0, "Home Depot"),

            # Safety Equipment
            ("Safety Equipment", "Full respirator", 1, 30.00, "Not just dust masks", 0, "Lowe's"),
            ("Safety Equipment", "Safety goggles", 2, 10.00, "Sealed type", 0, "Lowe's"),
            ("Safety Equipment", "Spray sock/head cover", 3, 5.00, "Protect hair/head", 0, "Lowe's"),
            ("Safety Equipment", "Disposable coveralls", 3, 10.00, "Full body protection", 0, "Lowe's"),
            ("Safety Equipment", "Heavy duty gloves", 2, 8.00, "Per pair", 0, "Lowe's"),

            # Surface Prep
            ("Surface Prep", "Sandpaper", 1, 10.00, "Various grits: 120, 180, 220", 0, "Walmart"),
            ("Surface Prep", "Spackle", 1, 8.00, "For repairs", 0, "Walmart"),
            ("Surface Prep", "TSP cleaner", 1, 10.00, "Wall preparation", 0, "Walmart"),
            ("Surface Prep", "Putty knife set", 1, 15.00, "Various sizes", 0, "Walmart"),

            # Clean-up
            ("Clean-up", "5-gallon buckets", 3, 5.00, "For clean-up", 0, "Home Depot"),
            ("Clean-up", "Paint thinner", 2, 15.00, "For equipment cleaning", 0, "Home Depot"),
            ("Clean-up", "Clean rags", 1, 10.00, "Large pack", 0, "Walmart"),

            # Tools
            ("Tools", "Multi-position ladder", 1, 150.00, "For stairwell and high areas", 0, "Lowe's"),
            ("Tools", "Step ladder", 1, 50.00, "For standard height walls", 0, "Lowe's"),
            ("Tools", "Screwdrivers", 1, 20.00, "Set for fixtures/plates", 0, "Walmart"),
            ("Tools", "Utility knife", 1, 10.00, "With extra blades", 0, "Walmart"),
            ("Tools", "Light extension cord", 2, 15.00, "For sprayer", 0, "Walmart")
        ]

        # Clear existing items (optional - remove if you want to preserve existing items)
        c.execute("DELETE FROM shopping_list")

        # Insert all items
        c.executemany("""
            INSERT INTO shopping_list (category, item, quantity, cost, notes, found, store)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, items)

        conn.commit()
        conn.close()
        print("Database populated successfully with all painting supplies.")
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise






if __name__ == "__main__":
    # Ensure data directory exists
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    
    try:
        # Initialize database
        setup_database()
        
        # Check if database is empty and populate sample data if needed
        with get_db_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM shopping_list").fetchone()[0]
            if count == 0:
                populate_sample_data()
        
        # Start server with live reload for development
        console.log("Starting server...")
        serve(host="127.0.0.1", port=8000, reload=True)
        
    except Exception as e:
        console.log(f"Failed to start application: {e}", style="bold red")
        raise