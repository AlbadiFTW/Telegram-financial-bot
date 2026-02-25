# 💰 Personal Finance Telegram Bot

A private Telegram bot for tracking shared expenses, debts, personal spending, and bank balance — built with Python + SQLite.

## ✨ Key Features

- 🤝 **Shared Expense Tracking** — Split bills, track who owes whom, get minimal settlement plans
- 💳 **Personal Finance** — Track balance, spending, income with automatic categorization
- 📊 **Smart Budgets** — Set monthly limits with 4-level alerts (75%, 90%, 100%+)
- 🚨 **Intelligent Alerts** — Percentage-based balance warnings (20%, 15%, 5%)
- 📅 **Auto Weekly Reports** — Every Friday at 9 AM GST with full financial snapshot
- 📥 **CSV Import** — Bulk import transactions from bank exports
- 🔒 **Private & Secure** — Owner-only access, local SQLite storage
- 🌍 **Multi-Language** — Supports Arabic keywords for auto-categorization

---

## ⚡ Quick Start (5 minutes)

### 1. Get a Bot Token from Telegram
1. Open Telegram → search **@BotFather**
2. Send `/newbot` → choose a name → get your `BOT_TOKEN`

### 2. Get Your Telegram User ID
1. Message **@userinfobot** in Telegram
2. Copy the numeric ID (e.g. `123456789`) — this is your `OWNER_ID`

### 3. Set Up Locally

```bash
# Clone / download these files into a folder
cd finance_bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

Create a `.env` file:
```env
BOT_TOKEN=your_telegram_bot_token_here
OWNER_ID=your_numeric_telegram_id
CURRENCY=AED
DB_PATH=finance.db
```

Then run:
```bash
# Option A: export manually
export BOT_TOKEN="..." OWNER_ID="123456" CURRENCY="AED"

# Option B: use python-dotenv (pip install python-dotenv)
# Add this to top of bot.py:  from dotenv import load_dotenv; load_dotenv()

python bot.py
```

You should see: `🤖 Bot started. Polling...`

---

## 📱 All Commands

### 🤝 Shared Expenses
| Command | Description |
|---------|-------------|
| `/paid 45 dinner @alice` | You paid 45 for Alice (she owes you) |
| `/paid 45 dinner` | You paid 45, just track it as personal spend |
| `/owe @bob 30 lunch` | You owe Bob 30 |
| `/owes @carol 50 trip` | Carol owes you 50 |
| `/balances` | See who owes whom |
| `/settle` | Minimal transfer plan to clear all debts |
| `/markpaid @alice 30` | Mark 30 as settled with Alice |
| `/markpaid @alice` | Mark ALL of Alice's debts as settled |
| `/history 15` | Last 15 transactions |
| `/clearall` | ⚠️ Reset all debts |

### 💳 Personal Finance
| Command | Description |
|---------|-------------|
| `/setbalance 5000` | Set your starting bank balance |
| `/balance` | Full financial snapshot with alerts |
| `/fixbalance 6500` | Directly correct balance (no transaction) |
| `/adjustbalance +500` | Adjust balance by relative amount |
| `/spend 45.5 food dinner` | Log a spend (auto-deducted from balance) |
| `/income 3000 salary` | Log income (added to balance) |
| `/budget food 1500` | Set 1500/month budget for food |
| `/budgets` | Budget usage with progress bars |
| `/summary` | This month's spending summary |
| `/summary jan` | January's summary |
| `/categories` | List all spending categories |
| `/weeklyreport` | Generate comprehensive weekly snapshot |

### 📥 CSV Import
Send any `.csv` file to the bot and it will auto-import all transactions.

**Supported CSV formats:**
```csv
date,description,amount
2024-01-15,Carrefour groceries,-145.50
2024-01-15,Salary,15000.00
2024-01-16,Uber,-23.00
```
```csv
date,description,debit,credit
2024-01-15,Carrefour,145.50,
2024-01-15,Salary,,15000.00
```
Negative amounts = spend. Positive = income. Works with ADCB, FAB, Emirates NBD exports.

---

## 🚨 Smart Alerts

The bot features intelligent percentage-based alerts to help you stay on track:

### Balance Alerts
When you spend money, the bot automatically checks your balance against your initial amount (set via `/setbalance`):
- 🟡 **20% remaining** — Warning alert
- 🔴 **15% remaining** — LOW balance alert  
- 🚨 **5% remaining** — CRITICAL alert

### Budget Alerts
Get notified as you approach your monthly category budgets:
- 🟡 **75%** — Approaching limit
- 🟠 **90%** — Budget alert
- 🔴 **100%+** — Over budget!

All alerts show exact amounts and percentages so you know exactly where you stand.

---

## 📅 Automatic Weekly Report

Every **Friday at 9:00 AM GST**, the bot automatically sends you a comprehensive financial snapshot including:
- Current balance with percentage alerts
- Monthly income and spending summary
- Top 5 spending categories
- Budget warnings for categories above 75% usage

You can also trigger the report anytime with `/weeklyreport`.

---

## 🏷️ Spending Categories
`food` · `transport` · `shopping` · `bills` · `entertainment` · `health` · `travel` · `other`

The bot auto-detects category from description keywords (supports Arabic too).

---

## 🚀 Keep It Running 24/7

### Option A: Railway (Free tier, easiest)
1. Push to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add environment variables in Railway dashboard
4. Done — it runs forever

### Option B: Fly.io
```bash
fly launch
fly secrets set BOT_TOKEN=... OWNER_ID=... CURRENCY=AED
fly deploy
```

### Option C: VPS / Your own server
```bash
# As a systemd service
sudo nano /etc/systemd/system/financebot.service
```
```ini
[Unit]
Description=Finance Telegram Bot
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/finance_bot
ExecStart=/home/ubuntu/finance_bot/venv/bin/python bot.py
Restart=always
Environment=BOT_TOKEN=...
Environment=OWNER_ID=...
Environment=CURRENCY=AED

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable financebot --now
```

### Option D: Raspberry Pi (always-on at home)
Same as VPS above. Zero cost, completely private.

---

## 🔒 Privacy

- `OWNER_ID` ensures only you can interact with the bot
- All data is stored locally in `finance.db` (SQLite)
- Nothing is sent to any third party

---

## 📊 Example Session

```
You: /setbalance 8000
Bot: ✅ Balance set to AED 8,000.00

You: /budget food 1500
Bot: ✅ Budget for food: AED 1,500.00/month

You: /spend 245 food groceries
Bot: 💸 Spent AED 245.00 on groceries [food]
     💳 Balance: AED 7,755.00
     🟡 Approaching limit food: AED 245.00/AED 1,500.00 (16%)

You: /paid 120 dinner @ahmed
Bot: ✅ Logged: You paid AED 120.00 for @ahmed (dinner)
     👤 @ahmed now owes you AED 120.00
     💳 Balance: AED 7,635.00

You: /adjustbalance +100
Bot: 🔧 Balance adjusted by +AED 100.00
     Before: AED 7,635.00
     After:  AED 7,735.00

You: /owe @sara 80 movie tickets
Bot: 📝 You owe @sara AED 80.00 for movie tickets

You: /settle
Bot: 💡 Minimal Settlement Plan
     👉 You pay @sara  AED 80.00
     👉 @ahmed pays you AED 120.00
     _2 transfer(s) to clear everything_

You: /budgets
Bot: 📊 Budget Status — February 2026
     🟡 food
     ████░░░░░░ 16%
     Spent AED 245.00 / AED 1,500.00

You: /balance
Bot: 💳 Your Financial Snapshot
     🏦 Bank Balance: AED 7,735.00
     💚 Others owe you: AED 120.00
     📈 Effective total: AED 7,855.00
     🔴 You owe others: AED 80.00
     📉 After paying debts: AED 7,655.00

You: /weeklyreport
Bot: 📅 Weekly Report — 26 Feb 2026
     💳 Balance: AED 7,735.00
     
     📈 This Month (February):
       Income:  AED 0.00
       Spent:   AED 365.00
       Net:     AED -365.00
     
     📊 Top Spending:
       • food: AED 365.00
```

---

## 🔧 Customization

**Add more auto-categories:** Edit `_CATEGORY_KEYWORDS` in `finance.py`

**Change alert thresholds:** In `bot.py`, modify the percentage checks:
- Balance alerts: Look for `pct <= 5`, `pct <= 15`, `pct <= 20`
- Budget alerts: Look for `pct >= 75`, `pct >= 90`, `pct >= 100`

**Change currency:** Set `CURRENCY=USD` (or any string) in `.env`

**Change weekly report time:** In `bot.py`, find `time=time(hour=9, minute=0)` and adjust

**Change weekly report day:** In `bot.py`, find `days=(4,)` (0=Monday, 4=Friday)
