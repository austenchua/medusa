"""Entry point: python -m bot.main"""
import datetime
import logging

from telegram import MenuButtonWebApp, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import config, db, handlers

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s", level=logging.INFO
)


async def post_init(app: Application) -> None:
    if config.WEBAPP_URL:
        # "Open App" button next to the message box in every private chat.
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open App", web_app=WebAppInfo(config.WEBAPP_URL))
        )
    if config.WEBAPP_PORT:
        from . import webserver
        await webserver.start(app)


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN environment variable (get one from @BotFather).")

    db.init_db()

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("new", handlers.cmd_new))
    app.add_handler(CommandHandler("today", handlers.cmd_today))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("report", handlers.cmd_report))
    app.add_handler(CommandHandler("pending", handlers.cmd_pending))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    app.add_handler(
        MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
                       handlers.on_message)
    )

    if app.job_queue:
        app.job_queue.run_daily(
            handlers.daily_digest,
            time=datetime.time(hour=config.DAILY_DIGEST_HOUR, tzinfo=config.TIMEZONE),
        )

    app.run_polling()


if __name__ == "__main__":
    main()
