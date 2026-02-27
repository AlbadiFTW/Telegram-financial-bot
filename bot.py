"""
💰 Personal Finance & Expense Tracker Bot
Telegram bot for tracking shared expenses, debts, and personal bank balance.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, date, time, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 fallback
    from backports.zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from database import Database
from finance import (
    minimal_transfers,
    compute_balances,
    parse_csv_transactions,
    categorize_description,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CURRENCY = os.getenv("CURRENCY", "AED")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID  = int(os.getenv("OWNER_ID", "0"))   # set this so only you can use the bot

db = Database("finance.db")

# ── Auth guard ────────────────────────────────────────────────────────────────
def owner_only(func):
    """Decorator: silently ignore requests from anyone other than the owner."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if OWNER_ID and update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🔒 Private bot — access denied.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt(amount: float) -> str:
    return f"{CURRENCY} {amount:,.2f}"

def now_str() -> str:
    return datetime.now().strftime("%d %b %Y, %H:%M")

# ── /start & /help ────────────────────────────────────────────────────────────
@owner_only
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Personal Finance Bot*\n\n"
        "Track shared expenses, debts, and your bank balance — all from Telegram.\n\n"
        "Type /help to see all commands."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@owner_only
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg1 = (
        "📖 *Help Guide — Part 1/4*\n\n"
        "🤝 *SHARED EXPENSES*\n"
        "Track debts and shared costs:\n\n"
        "*Recording Expenses:*\n"
        "• `/paid 50 dinner alice` — You paid for alice\n"
        "• `/owe alice 50 lunch` — You owe alice\n"
        "• `/owes alice 50 movie` — alice owes you\n\n"
        "*Managing Debts:*\n"
        "• `/balances` — See who owes whom\n"
        "• `/settle` — Get settlement plan\n"
        "• `/markpaid alice 50` — Clear a debt\n"
        "• `/clearall` — ⚠️ Reset everything"
    )
    
    msg2 = (
        "💳 *Help Guide — Part 2/4*\n"
        "*BALANCE & SPENDING*\n\n"
        "*Balance:*\n"
        "• `/setbalance 5000` — Set your balance\n"
        "• `/balance` — Check balance\n"
        "• `/fixbalance 6500` — Correct balance\n"
        "• `/adjustbalance +500` — Adjust by amount\n\n"
        "*Spending & Transactions:*\n"
        "• `/spend 25 food groceries` — Log expense\n"
        "• `/income 100 bonus` — Log income\n"
        "• `/history [n]` — Show last n transactions\n"
        "• `/delete <id>` — Delete transaction by ID\n"
        "• `/edit <id> [amt] [cat]` — Modify transaction"
    )
    
    msg3 = (
        "📊 *Help Guide — Part 3/4*\n"
        "*CATEGORIES & BUDGETS*\n\n"
        "*Manage Spending:*\n"
        "• `/clearcategory <cat> [month]` — Clear all in category\n"
        "• `/categories` — View available categories\n\n"
        "*Manage Budgets:*\n"
        "• `/budget food 300` — Set monthly limit\n"
        "• `/budgets` — View all budgets\n"
        "• `/deletebudget <cat>` — Remove budget\n\n"
        "*Reports:*\n"
        "• `/summary [month]` — Monthly breakdown\n"
        "• `/ytd [year]` — Year-to-date analysis"
    )
    
    msg4 = (
        "📋 *Help Guide — Part 4/4*\n"
        "*REPORTS & IMPORT*\n\n"
        "*Weekly Report:*\n"
        "• `/weeklyreport` — Full snapshot\n"
        "  _(Auto: Fridays 9 AM GST)_\n\n"
        f"💱 *Currency:* `{CURRENCY}`\n\n"
        "*CSV Import:*\n"
        "Send `.csv` file with columns:\n"
        "`date,amount,category,description`\n"
        "_Example:_ `2026-02-26,50.00,food,groceries`\n\n"
        "*Smart Alerts:*\n"
        "Balance: 🟡20% 🔴15% 🚨5% remaining\n"
        "Budget: 🟡75% 🟠90% 🔴100%"
    )
    
    await update.message.reply_text(msg1, parse_mode="Markdown")
    await update.message.reply_text(msg2, parse_mode="Markdown")
    await update.message.reply_text(msg3, parse_mode="Markdown")
    await update.message.reply_text(msg4, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════════════════════
# SHARED EXPENSES
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def paid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /paid 45.50 dinner @alice
    /paid 120 groceries          ← no person means just tracking your own spend
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/paid <amount> <description> [@person]`", parse_mode="Markdown")
        return

    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return

    # Collect description and optional @person from remaining args
    other_person = None
    desc_parts = []
    for a in args[1:]:
        if a.startswith("@"):
            other_person = a[1:]
        else:
            desc_parts.append(a)
    description = " ".join(desc_parts) or "expense"

    if other_person:
        # You paid on behalf of someone — they owe you
        db.add_debt(creditor="me", debtor=other_person, amount=amount, description=description)
        # Also log as personal spend
        category = categorize_description(description)
        db.add_transaction(amount=amount, t_type="spend", category=category, description=f"{description} (paid for @{other_person})")
        db.adjust_balance(-amount)
        new_bal = db.get_balance()
        bal_line = f"\n💳 Balance: *{fmt(new_bal)}*" if new_bal is not None else ""
        await update.message.reply_text(
            f"✅ Logged: You paid *{fmt(amount)}* for *@{other_person}* ({description})\n"
            f"👤 @{other_person} now owes you *{fmt(amount)}*{bal_line}",
            parse_mode="Markdown"
        )
    else:
        # Just a personal spend
        category = categorize_description(description)
        db.add_transaction(amount=amount, t_type="spend", category=category, description=description)
        db.adjust_balance(-amount)
        new_bal = db.get_balance()
        bal_line = f"\n💳 Balance: *{fmt(new_bal)}*" if new_bal is not None else ""
        budget_warn = _check_budget_warning(category)
        await update.message.reply_text(
            f"✅ Spent *{fmt(amount)}* on {description} [{category}]{bal_line}{budget_warn}",
            parse_mode="Markdown"
        )


@owner_only
async def owe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/owe @person 30 lunch"""
    if len(ctx.args) < 3:
        await update.message.reply_text("Usage: `/owe @person <amount> <description>`", parse_mode="Markdown")
        return
    person = ctx.args[0].lstrip("@")
    try:
        amount = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    description = " ".join(ctx.args[2:])
    db.add_debt(creditor=person, debtor="me", amount=amount, description=description)
    await update.message.reply_text(
        f"📝 You owe *@{person}*  *{fmt(amount)}* for {description}",
        parse_mode="Markdown"
    )


@owner_only
async def owes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/owes @person 30 lunch"""
    if len(ctx.args) < 3:
        await update.message.reply_text("Usage: `/owes @person <amount> <description>`", parse_mode="Markdown")
        return
    person = ctx.args[0].lstrip("@")
    try:
        amount = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    description = " ".join(ctx.args[2:])
    db.add_debt(creditor="me", debtor=person, amount=amount, description=description)
    await update.message.reply_text(
        f"📝 *@{person}* owes you *{fmt(amount)}* for {description}",
        parse_mode="Markdown"
    )


@owner_only
async def balances(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show net balance per person."""
    debts = db.get_all_debts()
    if not debts:
        await update.message.reply_text("🎉 No outstanding debts!")
        return

    net = compute_balances(debts)
    lines = ["📊 *Debt Balances*\n"]
    for person, amount in sorted(net.items(), key=lambda x: x[1]):
        if abs(amount) < 0.01:
            continue
        if amount > 0:
            lines.append(f"  💚 *@{person}* owes you *{fmt(amount)}*")
        else:
            lines.append(f"  🔴 You owe *@{person}* *{fmt(abs(amount))}*")

    if len(lines) == 1:
        await update.message.reply_text("🎉 All settled up!")
    else:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def settle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show the minimal set of transfers to clear all debts."""
    debts = db.get_all_debts()
    if not debts:
        await update.message.reply_text("🎉 Nothing to settle!")
        return

    net = compute_balances(debts)
    transfers = minimal_transfers(net)

    if not transfers:
        await update.message.reply_text("🎉 Already settled!")
        return

    lines = ["💡 *Minimal Settlement Plan*\n"]
    for payer, receiver, amount in transfers:
        if payer == "me":
            lines.append(f"  👉 You pay *@{receiver}*  *{fmt(amount)}*")
        elif receiver == "me":
            lines.append(f"  👉 *@{payer}* pays you *{fmt(amount)}*")
        else:
            lines.append(f"  👉 *@{payer}* → *@{receiver}*  *{fmt(amount)}*")

    lines.append(f"\n_{len(transfers)} transfer(s) to clear everything_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def markpaid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/markpaid @person 30  — reduce debt by amount (or clear fully if no amount)"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/markpaid @person [amount]`", parse_mode="Markdown")
        return
    person = ctx.args[0].lstrip("@")
    amount = float(ctx.args[1]) if len(ctx.args) > 1 else None
    cleared = db.clear_debt(person, amount)
    if cleared:
        msg = f"✅ Marked *{fmt(cleared)}* as settled with *@{person}*"
    else:
        msg = f"⚠️ No debt found with @{person}"
    await update.message.reply_text(msg, parse_mode="Markdown")


@owner_only
async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show last n transactions with IDs for deletion."""
    n = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else 10
    rows = db.get_transactions(limit=n)
    if not rows:
        await update.message.reply_text("No transactions yet.")
        return
    lines = [f"📜 *Last {n} Transactions*\n"]
    for r in rows:
        icon = "💸" if r["type"] == "spend" else "💰"
        lines.append(f"  `#{r['id']}` {icon} *{fmt(r['amount'])}* — {r['description']} [{r['category']}]\n    _{r['created_at']}_")
    lines.append("\n💡 Use `/delete <id>` to remove a transaction")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def delete_transaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/delete 42 — Delete a transaction by ID"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/delete <transaction_id>`\nGet transaction IDs from `/history`", parse_mode="Markdown")
        return
    
    try:
        tx_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Transaction ID must be a number.")
        return
    
    # Get transaction before deletion
    tx_data = db.get_transaction_by_id(tx_id)
    
    if not tx_data:
        await update.message.reply_text(f"⚠️ Transaction #{tx_id} not found.")
        return
    
    if db.delete_transaction(tx_id):
        icon = "💸" if tx_data["type"] == "spend" else "💰"
        await update.message.reply_text(
            f"✅ Deleted transaction #{tx_id}\n"
            f"{icon} *{fmt(tx_data['amount'])}* — {tx_data['description']} [{tx_data['category']}]",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Failed to delete transaction #{tx_id}")


@owner_only
async def edit_transaction_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/edit 42 25.50 food groceries - Edit transaction amount, category, and/or description"""
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/edit <id> [amount] [category] [description]`\n"
            "Only provide fields you want to change.\n"
            "_Example:_ `/edit 42 25.50 food groceries`",
            parse_mode="Markdown"
        )
        return
    
    try:
        tx_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Transaction ID must be a number.")
        return
    
    # Get original transaction
    tx_data = db.get_transaction_by_id(tx_id)
    
    if not tx_data:
        await update.message.reply_text(f"⚠️ Transaction #{tx_id} not found.")
        return
    
    # Parse arguments
    amount = None
    category = None
    description_parts = []
    
    for i, arg in enumerate(ctx.args[1:]):
        if i == 0:
            try:
                amount = float(arg)
                continue
            except ValueError:
                pass
        
        if i == 1 or (i > 1 and category is None):
            # Could be category or start of description
            if arg.lower() in ["food", "transport", "shopping", "bills", "entertainment", "health", "travel", "other"]:
                category = arg.lower()
                continue
        
        description_parts.append(arg)
    
    description = " ".join(description_parts) if description_parts else None
    
    # Update transaction
    updated = db.edit_transaction(tx_id, amount, category, description)
    
    if updated:
        icon = "💸" if updated["type"] == "spend" else "💰"
        
        # Show what changed
        changes = []
        if amount is not None and amount != tx_data["amount"]:
            changes.append(f"Amount: *{fmt(tx_data['amount'])}* → *{fmt(updated['amount'])}*")
        if category is not None and category != tx_data["category"]:
            changes.append(f"Category: *{tx_data['category']}* → *{updated['category']}*")
        if description is not None and description != tx_data["description"]:
            changes.append(f"Description: _{tx_data['description']}_ → _{updated['description']}_")
        
        change_text = "\n".join(changes) if changes else "_No changes made_"
        
        await update.message.reply_text(
            f"✅ Updated transaction #{tx_id}\n"
            f"{icon} {fmt(updated['amount'])} [{updated['category']}]\n\n"
            f"{change_text}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Failed to update transaction #{tx_id}")


@owner_only
async def clearcategory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/clearcategory food or /clearcategory food 2026-02"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/clearcategory <category> [month]`\nMonth format: `YYYY-MM` (default: current month)", parse_mode="Markdown")
        return
    
    category = ctx.args[0].lower()
    today = date.today()
    year, month = today.year, today.month
    
    if len(ctx.args) > 1:
        try:
            y, m = ctx.args[1].split("-")
            year, month = int(y), int(m)
        except:
            await update.message.reply_text("❌ Month must be in format `YYYY-MM` (e.g., `2026-02`)", parse_mode="Markdown")
            return
    
    # Get spending before deletion
    rows = db.get_monthly_transactions(year, month)
    cat_spend = sum(r["amount"] for r in rows if r["type"] == "spend" and r["category"] == category)
    
    if cat_spend == 0:
        await update.message.reply_text(f"⚠️ No spending found in *{category}* for {date(year, month, 1).strftime('%B %Y')}.", parse_mode="Markdown")
        return
    
    count = db.delete_category_transactions(category, year, month)
    if count > 0:
        await update.message.reply_text(
            f"✅ Cleared *{count}* transactions in *{category}*\n"
            f"💸 Total removed: *{fmt(cat_spend)}*\n"
            f"Month: {date(year, month, 1).strftime('%B %Y')}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Failed to clear {category} transactions")


@owner_only
async def clearall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reset all debts (with confirmation)."""
    db.clear_all_debts()
    await update.message.reply_text("🧹 All debts cleared! Starting fresh.")


# ══════════════════════════════════════════════════════════════════════════════
# PERSONAL FINANCE
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def setbalance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/setbalance 5000"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/setbalance <amount>`", parse_mode="Markdown")
        return
    try:
        amount = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    db.set_balance(amount)
    db.set_initial_balance(amount)  # Track for percentage alerts
    await update.message.reply_text(f"✅ Balance set to *{fmt(amount)}*", parse_mode="Markdown")


@owner_only
async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/balance — show current bank balance"""
    bal = db.get_balance()
    if bal is None:
        await update.message.reply_text("No balance set yet. Use `/setbalance <amount>` to start.", parse_mode="Markdown")
        return

    # Also show what you're owed / owe
    debts = db.get_all_debts()
    net = compute_balances(debts)
    owed_to_me = sum(v for v in net.values() if v > 0)
    i_owe      = sum(abs(v) for v in net.values() if v < 0)

    lines = [
        "💳 *Your Financial Snapshot*\n",
        f"🏦 Bank Balance: *{fmt(bal)}*",
    ]
    
    # Percentage-based alert
    initial = db.get_initial_balance()
    if initial and initial > 0:
        pct = (bal / initial) * 100
        if pct <= 5:
            lines.append(f"🚨 *CRITICAL: {pct:.1f}% of initial balance remaining!*")
        elif pct <= 15:
            lines.append(f"🔴 *LOW: {pct:.1f}% of initial balance remaining*")
        elif pct <= 20:
            lines.append(f"🟡 *Warning: {pct:.1f}% of initial balance remaining*")
    
    if owed_to_me > 0:
        lines.append(f"💚 Others owe you: *{fmt(owed_to_me)}*")
        lines.append(f"📈 Effective total: *{fmt(bal + owed_to_me)}*")
    if i_owe > 0:
        lines.append(f"🔴 You owe others: *{fmt(i_owe)}*")
        lines.append(f"📉 After paying debts: *{fmt(bal - i_owe)}*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def fixbalance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/fixbalance 6500 — directly correct balance without transaction"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/fixbalance <correct_amount>`", parse_mode="Markdown")
        return
    try:
        new_amount = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    
    old_bal = db.get_balance()
    db.set_balance(new_amount)
    
    if old_bal is not None:
        diff = new_amount - old_bal
        await update.message.reply_text(
            f"🔧 Balance corrected\n"
            f"Before: *{fmt(old_bal)}*\n"
            f"After:  *{fmt(new_amount)}*\n"
            f"Diff:   *{fmt(diff)}*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"✅ Balance set to *{fmt(new_amount)}*", parse_mode="Markdown")


@owner_only
async def adjustbalance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/adjustbalance +500 or /adjustbalance -200 — adjust balance by relative amount"""
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/adjustbalance <+/- amount>`\n"
            "Examples: `/adjustbalance +500` or `/adjustbalance -200`",
            parse_mode="Markdown"
        )
        return
    
    bal = db.get_balance()
    if bal is None:
        await update.message.reply_text("No balance set. Use `/setbalance <amount>` first.", parse_mode="Markdown")
        return
    
    try:
        adjustment = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number (e.g., +500 or -200).")
        return
    
    new_bal = bal + adjustment
    db.set_balance(new_bal)
    
    symbol = "+" if adjustment > 0 else ""
    await update.message.reply_text(
        f"🔧 Balance adjusted by *{symbol}{fmt(adjustment)}*\n"
        f"Before: *{fmt(bal)}*\n"
        f"After:  *{fmt(new_bal)}*",
        parse_mode="Markdown"
    )


@owner_only
async def spend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/spend 45.5 food dinner at restaurant"""
    if len(ctx.args) < 3:
        await update.message.reply_text(
            "Usage: `/spend <amount> <category> <description>`\n"
            "Categories: food, transport, shopping, bills, entertainment, health, other",
            parse_mode="Markdown"
        )
        return
    try:
        amount = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    category    = ctx.args[1].lower()
    description = " ".join(ctx.args[2:])

    db.add_transaction(amount=amount, t_type="spend", category=category, description=description)
    db.adjust_balance(-amount)
    new_bal = db.get_balance()

    bal_line     = f"\n💳 Balance: *{fmt(new_bal)}*" if new_bal is not None else ""
    budget_warn  = _check_budget_warning(category)

    # Percentage-based balance alert
    low_warn = ""
    if new_bal is not None:
        initial = db.get_initial_balance()
        if initial and initial > 0:
            pct = (new_bal / initial) * 100
            if pct <= 5:
                low_warn = f"\n🚨 *CRITICAL: {pct:.1f}% of initial balance remaining!*"
            elif pct <= 15:
                low_warn = f"\n🔴 *LOW: {pct:.1f}% of initial balance remaining*"
            elif pct <= 20:
                low_warn = f"\n🟡 *Warning: {pct:.1f}% of initial balance remaining*"

    await update.message.reply_text(
        f"💸 Spent *{fmt(amount)}* on {description} [{category}]{bal_line}{budget_warn}{low_warn}",
        parse_mode="Markdown"
    )


@owner_only
async def income(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/income 3000 salary"""
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/income <amount> <description>`", parse_mode="Markdown")
        return
    try:
        amount = float(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    description = " ".join(ctx.args[1:])
    db.add_transaction(amount=amount, t_type="income", category="income", description=description)
    db.adjust_balance(amount)
    new_bal = db.get_balance()
    bal_line = f"\n💳 Balance: *{fmt(new_bal)}*" if new_bal is not None else ""
    await update.message.reply_text(
        f"💰 Income *{fmt(amount)}* added — {description}{bal_line}",
        parse_mode="Markdown"
    )


@owner_only
async def set_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/budget food 1000"""
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/budget <category> <monthly_amount>`", parse_mode="Markdown")
        return
    category = ctx.args[0].lower()
    try:
        amount = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    db.set_budget(category, amount)
    await update.message.reply_text(f"✅ Budget for *{category}*: *{fmt(amount)}/month*", parse_mode="Markdown")


@owner_only
async def budgets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show budget usage for current month."""
    all_budgets = db.get_budgets()
    if not all_budgets:
        await update.message.reply_text("No budgets set. Use `/budget <category> <amount>` to create one.", parse_mode="Markdown")
        return

    today = date.today()
    lines = [f"📊 *Budget Status — {today.strftime('%B %Y')}*\n"]
    for cat, limit in all_budgets.items():
        spent = db.get_monthly_spend(cat, today.year, today.month)
        pct   = (spent / limit * 100) if limit else 0
        bar   = _progress_bar(pct)
        status = "🔴 OVER" if pct > 100 else ("�" if pct > 90 else ("🟡" if pct > 80 else "🟢"))
        lines.append(f"{status} *{cat}*")
        lines.append(f"   {bar} {pct:.0f}%")
        lines.append(f"   {fmt(spent)} / {fmt(limit)}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def deletebudget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/deletebudget food"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/deletebudget <category>`", parse_mode="Markdown")
        return
    
    category = ctx.args[0].lower()
    if db.delete_budget(category):
        await update.message.reply_text(f"✅ Budget for *{category}* deleted.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ No budget found for *{category}*", parse_mode="Markdown")


@owner_only
async def summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/summary or /summary jan or /summary 2025-01"""
    today = date.today()
    year, month = today.year, today.month

    if ctx.args:
        arg = ctx.args[0].lower()
        month_names = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
                       "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        if arg in month_names:
            month = month_names[arg]
        elif "-" in arg:
            try:
                y, m = arg.split("-")
                year, month = int(y), int(m)
            except:
                pass

    rows = db.get_monthly_transactions(year, month)
    if not rows:
        await update.message.reply_text(f"No transactions for {date(year, month, 1).strftime('%B %Y')}.")
        return

    total_spend  = sum(r["amount"] for r in rows if r["type"] == "spend")
    total_income = sum(r["amount"] for r in rows if r["type"] == "income")
    net_change = total_income - total_spend

    # Calculate starting and ending balance
    current_bal = db.get_balance()
    if current_bal is not None:
        starting_balance = current_bal - net_change
        ending_balance = current_bal
    else:
        starting_balance = None
        ending_balance = None

    # Group by category
    cats: dict[str, float] = {}
    for r in rows:
        if r["type"] == "spend":
            cats[r["category"]] = cats.get(r["category"], 0) + r["amount"]

    lines = [f"📅 *Summary — {date(year, month, 1).strftime('%B %Y')}*\n"]
    
    # Balance flow
    if starting_balance is not None:
        lines.append(f"🏦 *Balance Flow:*")
        lines.append(f"   Start: *{fmt(starting_balance)}*")
        lines.append(f"   + Income:  *{fmt(total_income)}*")
        lines.append(f"   − Spent:   *{fmt(total_spend)}*")
        lines.append(f"   = End:     *{fmt(ending_balance)}*")
        lines.append("")
    else:
        lines.append(f"💰 Income:  *{fmt(total_income)}*")
        lines.append(f"💸 Spent:   *{fmt(total_spend)}*")
        lines.append(f"📈 Net:     *{fmt(net_change)}*")
        lines.append("")
    
    # Category breakdown
    if cats:
        lines.append("*Spending by Category:*")
        for cat, amt in sorted(cats.items(), key=lambda x: -x[1]):
            pct = amt / total_spend * 100 if total_spend else 0
            lines.append(f"   • {cat}: *{fmt(amt)}* ({pct:.0f}%)")
        lines.append("")

    # Budget status
    budgets = db.get_budgets()
    if budgets:
        lines.append("*Budget Status:*")
        for cat, limit in budgets.items():
            spent = db.get_monthly_spend(cat, year, month)
            pct = (spent / limit * 100) if limit else 0
            status = "🔴" if pct > 100 else ("🟠" if pct > 90 else ("🟡" if pct > 75 else "🟢"))
            lines.append(f"   {status} {cat}: {fmt(spent)} / {fmt(limit)} ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def ytd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/ytd [year] — Year-to-date summary with monthly breakdown"""
    today = date.today()
    year = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else today.year
    
    # Determine how many months to show
    # If querying current year, show up to current month
    # If querying past year, show all 12 months
    max_month = today.month if year == today.year else 12
    
    # Get all transactions for the year
    all_rows = db.get_yearly_transactions(year)
    if not all_rows:
        await update.message.reply_text(f"ℹ️ No transactions found for {year}.")
        return
    
    # Group by month
    monthly_data: dict[int, dict] = {}
    for month in range(1, max_month + 1):
        rows = [r for r in all_rows if r['created_at'].startswith(f"{year}-{month:02d}")]
        monthly_data[month] = {
            'spend': sum(r["amount"] for r in rows if r["type"] == "spend"),
            'income': sum(r["amount"] for r in rows if r["type"] == "income"),
            'count': len(rows)
        }
    
    # Calculate YTD totals
    ytd_spend = sum(m['spend'] for m in monthly_data.values())
    ytd_income = sum(m['income'] for m in monthly_data.values())
    
    lines = [f"📊 *Year-to-Date Summary — {year}*\n"]
    lines.append(f"💰 YTD Income:   *{fmt(ytd_income)}*")
    lines.append(f"💸 YTD Spent:    *{fmt(ytd_spend)}*")
    lines.append(f"📈 YTD Net:      *{fmt(ytd_income - ytd_spend)}*")
    lines.append("")
    
    lines.append("*Monthly Breakdown:*")
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    for month in range(1, max_month + 1):
        data = monthly_data[month]
        month_net = data['income'] - data['spend']
        
        # Calculate days in month
        if month < 12:
            next_month = date(year, month + 1, 1)
        else:
            next_month = date(year + 1, 1, 1)
        last_day_of_month = (next_month - timedelta(days=1)).day
        
        days_in_month = last_day_of_month if month != today.month or year != today.year else today.day
        daily_avg = data['spend'] / days_in_month if days_in_month > 0 else 0
        
        lines.append(
            f"  {month_names[month]}: 💰{fmt(data['income'])} | 💸{fmt(data['spend'])} | 📈{fmt(month_net)} | ⌛{fmt(daily_avg)}/day"
        )
    
    lines.append("")
    
    # Budget comparison
    budgets = db.get_budgets()
    if budgets:
        lines.append("*Budget Performance (YTD):*")
        for cat, monthly_limit in sorted(budgets.items()):
            ytd_cat_spend = sum(
                r["amount"] for r in all_rows 
                if r["type"] == "spend" and r["category"] == cat
            )
            ytd_budget = monthly_limit * max_month  # Total budget for months shown
            pct = (ytd_cat_spend / ytd_budget * 100) if ytd_budget > 0 else 0
            status = "🔴" if pct > 100 else ("🟠" if pct > 90 else ("🟡" if pct > 75 else "🟢"))
            lines.append(f"  {status} {cat}: {fmt(ytd_cat_spend)} / {fmt(ytd_budget)} ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏷️ *Spending Categories*\n\n"
        "• `food` — Restaurants, groceries, coffee\n"
        "• `transport` — Fuel, taxi, parking\n"
        "• `shopping` — Clothes, electronics, etc.\n"
        "• `bills` — Utilities, subscriptions\n"
        "• `entertainment` — Movies, outings\n"
        "• `health` — Medical, pharmacy, gym\n"
        "• `travel` — Flights, hotels\n"
        "• `other` — Anything else\n\n"
        "Use any of these in `/spend` or `/budget`."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY REPORT
# ══════════════════════════════════════════════════════════════════════════════

def generate_weekly_report() -> str:
    """Generate a comprehensive weekly financial report."""
    today = date.today()
    year, month = today.year, today.month
    
    # Balance info
    bal = db.get_balance()
    initial = db.get_initial_balance()
    bal_section = "💳 *Balance:* Not set" if bal is None else f"💳 *Balance:* {fmt(bal)}"
    
    if bal is not None and initial and initial > 0:
        pct = (bal / initial) * 100
        if pct <= 5:
            bal_section += f"\n🚨 *CRITICAL: {pct:.1f}% remaining!*"
        elif pct <= 15:
            bal_section += f"\n🔴 *LOW: {pct:.1f}% remaining*"
        elif pct <= 20:
            bal_section += f"\n🟡 *Warning: {pct:.1f}% remaining*"
    
    # Monthly spending summary
    rows = db.get_monthly_transactions(year, month)
    total_spend = sum(r["amount"] for r in rows if r["type"] == "spend")
    total_income = sum(r["amount"] for r in rows if r["type"] == "income")
    
    # Top spending categories
    cats: dict[str, float] = {}
    for r in rows:
        if r["type"] == "spend":
            cats[r["category"]] = cats.get(r["category"], 0) + r["amount"]
    
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:5]
    cat_lines = []
    for cat, amt in top_cats:
        cat_lines.append(f"  • {cat}: {fmt(amt)}")
    
    cat_section = "📊 *Top Spending:*\n" + "\n".join(cat_lines) if cat_lines else "📊 *Top Spending:* None this month"
    
    # Budget warnings
    budgets = db.get_budgets()
    budget_warnings = []
    if budgets:
        for cat, limit in budgets.items():
            spent = db.get_monthly_spend(cat, year, month)
            pct = (spent / limit * 100) if limit else 0
            if pct >= 100:
                budget_warnings.append(f"🔴 *{cat}*: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)")
            elif pct >= 90:
                budget_warnings.append(f"🟠 *{cat}*: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)")
            elif pct >= 75:
                budget_warnings.append(f"🟡 *{cat}*: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)")
    
    budget_section = ""
    if budget_warnings:
        budget_section = "\n\n⚠️ *Budget Alerts:*\n" + "\n".join(budget_warnings)
    
    # Compose report
    report = (
        f"📅 *Weekly Report — {today.strftime('%d %b %Y')}*\n\n"
        f"{bal_section}\n\n"
        f"📈 *This Month ({today.strftime('%B')}):*\n"
        f"  Income:  {fmt(total_income)}\n"
        f"  Spent:   {fmt(total_spend)}\n"
        f"  Net:     {fmt(total_income - total_spend)}\n\n"
        f"{cat_section}"
        f"{budget_section}"
    )
    
    return report


@owner_only
async def weeklyreport(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/weeklyreport — Generate weekly financial snapshot."""
    report = generate_weekly_report()
    await update.message.reply_text(report, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
# CSV IMPORT
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle CSV file uploads for bulk transaction import."""
    doc = update.message.document
    if not doc.file_name.endswith(".csv"):
        await update.message.reply_text("Please send a CSV file to import transactions.")
        return

    await update.message.reply_text("⏳ Processing your CSV...")
    file = await doc.get_file()
    csv_bytes = await file.download_as_bytearray()
    csv_text  = csv_bytes.decode("utf-8", errors="replace")

    transactions, errors = parse_csv_transactions(csv_text)
    if not transactions:
        await update.message.reply_text(
            "❌ Couldn't parse CSV. Expected columns: `date, description, amount` (negative = spend, positive = income).",
            parse_mode="Markdown"
        )
        return

    imported = 0
    total_spend = 0.0
    total_income = 0.0
    for t in transactions:
        category = categorize_description(t["description"])
        t_type   = "income" if t["amount"] > 0 else "spend"
        db.add_transaction(
            amount=abs(t["amount"]),
            t_type=t_type,
            category=category,
            description=t["description"],
            created_at=t.get("date")
        )
        db.adjust_balance(t["amount"])
        if t_type == "spend":
            total_spend += abs(t["amount"])
        else:
            total_income += t["amount"]
        imported += 1

    bal = db.get_balance()
    bal_line = f"\n💳 Current balance: *{fmt(bal)}*" if bal is not None else ""
    warn_line = f"\n⚠️ {len(errors)} rows skipped (bad format)" if errors else ""

    await update.message.reply_text(
        f"✅ Imported *{imported}* transactions\n"
        f"💸 Spend: *{fmt(total_spend)}*\n"
        f"💰 Income: *{fmt(total_income)}*"
        f"{bal_line}{warn_line}",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _progress_bar(pct: float, width: int = 10) -> str:
    filled = int(min(pct, 100) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _check_budget_warning(category: str) -> str:
    """Check budget status and return warning if approaching/over limit."""
    budgets = db.get_budgets()
    if category not in budgets:
        return ""
    today = date.today()
    spent = db.get_monthly_spend(category, today.year, today.month)
    limit = budgets[category]
    pct   = spent / limit * 100 if limit else 0
    if pct >= 100:
        return f"\n🔴 *Over budget!* {category}: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)"
    elif pct >= 90:
        return f"\n🟠 *Budget alert!* {category}: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)"
    elif pct >= 75:
        return f"\n🟡 *Approaching limit* {category}: {fmt(spent)}/{fmt(limit)} ({pct:.0f}%)"
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULED TASKS
# ══════════════════════════════════════════════════════════════════════════════

async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled callback to send weekly report every Friday at 9 AM GST."""
    if not OWNER_ID:
        return
    
    report = generate_weekly_report()
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=report,
            parse_mode="Markdown"
        )
        logger.info("📅 Weekly report sent successfully")
    except Exception as e:
        logger.error(f"Failed to send weekly report: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN environment variable")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_cmd))

    # Shared expenses
    app.add_handler(CommandHandler("paid",        paid))
    app.add_handler(CommandHandler("owe",         owe))
    app.add_handler(CommandHandler("owes",        owes))
    app.add_handler(CommandHandler("balances",    balances))
    app.add_handler(CommandHandler("settle",      settle))
    app.add_handler(CommandHandler("markpaid",    markpaid))
    app.add_handler(CommandHandler("history",     history))
    app.add_handler(CommandHandler("delete",      delete_transaction))
    app.add_handler(CommandHandler("edit",        edit_transaction_cmd))
    app.add_handler(CommandHandler("clearcategory", clearcategory))
    app.add_handler(CommandHandler("clearall",    clearall))

    # Personal finance
    app.add_handler(CommandHandler("setbalance",  setbalance))
    app.add_handler(CommandHandler("balance",     balance))
    app.add_handler(CommandHandler("fixbalance",  fixbalance))
    app.add_handler(CommandHandler("adjustbalance", adjustbalance))
    app.add_handler(CommandHandler("spend",       spend))
    app.add_handler(CommandHandler("income",      income))
    app.add_handler(CommandHandler("budget",      set_budget))
    app.add_handler(CommandHandler("budgets",     budgets))
    app.add_handler(CommandHandler("deletebudget", deletebudget))
    app.add_handler(CommandHandler("summary",     summary))
    app.add_handler(CommandHandler("ytd",         ytd))
    app.add_handler(CommandHandler("categories",  categories))
    app.add_handler(CommandHandler("weeklyreport", weeklyreport))

    # CSV import via document
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Schedule weekly report every Friday at 9:00 AM GST (UTC+4)
    if OWNER_ID:
        job_queue = app.job_queue
        gst_tz = ZoneInfo("Asia/Dubai")  # GST timezone
        job_queue.run_daily(
            send_weekly_report,
            time=time(hour=9, minute=0, tzinfo=gst_tz),
            days=(4,)  # Friday (0=Monday, 4=Friday)
        )
        logger.info("📅 Scheduled weekly report for Fridays at 9:00 AM GST")

    logger.info("🤖 Bot started. Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
