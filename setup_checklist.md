# Setup Checklist

Use this checklist to track your progress while configuring and deploying the **Productivity Hub Bot**:

* [ ] **Create Telegram Bot**
  * Message [@BotFather](https://t.me/BotFather) on Telegram and run `/newbot`. Follow the steps to choose a name and username.

* [ ] **Copy BOT_TOKEN**
  * Copy the HTTP API token provided by BotFather (e.g., `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

* [ ] **Find Telegram User ID**
  * Message [@userinfobot](https://t.me/userinfobot) or [@raw_data_bot](https://t.me/raw_data_bot) on Telegram to get your numeric Telegram user ID (e.g., `987654321`).

* [ ] **Set OWNER_ID**
  * Note down this ID to set as your primary bot administrator.

* [ ] **Configure .env**
  * Duplicate `.env.example` as a new file named `.env` and fill in:
    * `BOT_TOKEN`
    * `OWNER_ID`
    * `SECRET_KEY` (generate a unique secure string)

* [ ] **Install requirements**
  * Run the command to install packages: `pip install -r requirements.txt`.

* [ ] **Run database initialization**
  * Initialize sqlite database structures: `python -c "from services.database_service import init_db; init_db()"`.

* [ ] **Start bot**
  * Run the bot locally: `python bot.py`.

* [ ] **Deploy to Render**
  * Connect your GitHub repository to Render, create a new Web Service using Python runtime, mount a disk volume for `/app/database`, and set environment variables.
