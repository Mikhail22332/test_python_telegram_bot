import logging
from telegram import (
    Update,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from config import TOKEN, COURIERS, REASONS, NORMALIZATION_FACTOR

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

STATE_Q1, STATE_FLOW = range(2)

STEPS = {
    "driver": {
        "title": "Выберите водителя",
        "mode": "list",
        "source": COURIERS,
        "save_to": "driver",
        "next": "reason",
    },
    "reason": {
        "title": "Выберите причину",
        "mode": "list",
        "source": REASONS,
        "save_to": "reason",
        "next": "norm",
    },
    "norm": {
        "title": "Выберите нормализацию",
        "mode": "list",
        "source": NORMALIZATION_FACTOR,
        "save_to": "norm",
        "next": "more",
    },
    "more": {
        "title": "Хотите закончить выбор водителей?",
        "mode": "binary",
        "yes_next": None,
        "no_next": "driver",
    },
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info("start: user_id=%s", user_id)

    context.user_data.clear()
    context.user_data["incidents"] = []
    context.user_data["available_driver_ids"] = [d["id"] for d in COURIERS]

    kb = [[
        InlineKeyboardButton("Да", callback_data="q1_yes"),
        InlineKeyboardButton("Нет", callback_data="q1_no"),
    ]]
    await update.message.reply_text(
        'Вопрос 1: "Все ли водители вышли на работу?"',
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return STATE_Q1


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else None
    logger.info("done: user_id=%s", user_id)

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text("Опрос завершён. Спасибо!")
    elif update.message:
        await update.message.reply_text(
            "Опрос прерван.",
            reply_markup=ReplyKeyboardRemove(),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_q1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    logger.info(
        "handle_q1: user_id=%s, data=%s",
        q.from_user.id,
        q.data,
    )

    if q.data == "q1_yes":
        await q.message.reply_text("Отлично, все вышли. Опрос завершён.")
        return ConversationHandler.END

    if q.data == "q1_no":
        await q.message.reply_text("Не все вышли. Делаем выбор водителей.")
        await start_step(update, context, "driver")
        return STATE_FLOW


async def start_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step_name: str,
) -> None:
    q = update.callback_query
    step = STEPS[step_name]
    mode = step["mode"]
    context.user_data["step"] = step_name

    logger.info(
        "start_step: user_id=%s, step=%s, mode=%s",
        q.from_user.id,
        step_name,
        mode,
    )

    if mode == "list":
        items = step["source"]
        if step_name == "driver":
            allowed = context.user_data.get("available_driver_ids", [])
            items = [d for d in items if d["id"] in allowed]
            logger.info(
                "start_step: available_driver_ids=%s, items_count=%s",
                allowed,
                len(items),
            )
            if not items:
                await q.message.reply_text("Все водители уже выбраны.")
                await send_summary(update, context)
                return
        kb = [[
            InlineKeyboardButton(
                item["name"],
                callback_data=f"{step_name}:{item['id']}",
            )
            for item in items
        ]]
    else:
        kb = [[
            InlineKeyboardButton("Да", callback_data="yes"),
            InlineKeyboardButton("Нет", callback_data="no"),
        ]]

    await q.message.reply_text(
        step["title"],
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    step_name = context.user_data.get("step")
    step = STEPS.get(step_name)

    logger.info(
        "handle_step: user_id=%s, step=%s, data=%s",
        q.from_user.id,
        step_name,
        q.data,
    )

    if not step:
        await q.message.reply_text("Ошибка состояния. Начните /start заново.")
        context.user_data.clear()
        return ConversationHandler.END

    if step["mode"] == "list":
        return await handle_list_step(update, context, step_name, step)
    else:
        return await handle_binary_step(update, context, step)


async def handle_list_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step_name: str,
    step: dict,
) -> int:
    q = update.callback_query
    try:
        _, id_str = q.data.split(":", 1)
        item_id = int(id_str)
    except (ValueError, IndexError):
        logger.warning(
            "handle_list_step: bad data='%s', user_id=%s",
            q.data,
            q.from_user.id,
        )
        await q.message.reply_text("Не удалось распознать выбор.")
        return STATE_FLOW

    source = step["source"]
    obj = next((x for x in source if x["id"] == item_id), None)
    if not obj:
        logger.warning(
            "handle_list_step: item not found id=%s, step=%s, user_id=%s",
            item_id,
            step_name,
            q.from_user.id,
        )
        await q.message.reply_text("Элемент не найден.")
        return STATE_FLOW

    context.user_data[step["save_to"]] = obj

    if step_name == "driver":
        ids = context.user_data.get("available_driver_ids", [])
        if item_id in ids:
            ids.remove(item_id)
        context.user_data["available_driver_ids"] = ids
        logger.info(
            "handle_list_step: picked_driver_id=%s, remaining_ids=%s, user_id=%s",
            item_id,
            ids,
            q.from_user.id,
        )

    logger.info(
        "handle_list_step: user_id=%s, step=%s, picked_name=%s",
        q.from_user.id,
        step_name,
        obj["name"],
    )

    next_step = step["next"]
    if not next_step:
        await send_summary(update, context)
        return ConversationHandler.END

    await q.message.reply_text(f"Вы выбрали {obj['name']}.")
    await start_step(update, context, next_step)
    return STATE_FLOW


async def handle_binary_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: dict,
) -> int:
    q = update.callback_query
    answer = q.data

    driver = context.user_data.get("driver")
    reason = context.user_data.get("reason")
    norm = context.user_data.get("norm")

    if driver and reason:
        incidents = context.user_data.setdefault("incidents", [])
        incidents.append(
            {"driver": driver, "reason": reason, "norm": norm}
        )
        logger.info(
            "handle_binary_step: added_incident user_id=%s, driver=%s, reason=%s, norm=%s, total=%s",
            q.from_user.id,
            driver["name"],
            reason["name"],
            norm["name"] if norm else None,
            len(incidents),
        )

    if answer == "yes":
        next_step = step.get("yes_next")
    elif answer == "no":
        next_step = step.get("no_next")
    else:
        logger.warning(
            "handle_binary_step: unknown answer='%s', user_id=%s",
            answer,
            q.from_user.id,
        )
        await q.message.reply_text("Неизвестный ответ.")
        return STATE_FLOW

    logger.info(
        "handle_binary_step: user_id=%s, answer=%s, next_step=%s",
        q.from_user.id,
        answer,
        next_step,
    )

    if not next_step:
        await send_summary(update, context)
        return ConversationHandler.END

    await start_step(update, context, next_step)
    return STATE_FLOW


async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    incidents = context.user_data.get("incidents") or []

    logger.info(
        "send_summary: user_id=%s, incidents_count=%s",
        q.from_user.id,
        len(incidents),
    )

    if not incidents:
        driver = context.user_data.get("driver")
        reason = context.user_data.get("reason")
        norm = context.user_data.get("norm")
        if not driver or not reason:
            logger.warning(
                "send_summary: not enough data user_id=%s, driver=%r, reason=%r, norm=%r",
                q.from_user.id,
                driver,
                reason,
                norm,
            )
            await q.message.reply_text(
                "Недостаточно данных для формирования инцидента. Начните /start заново."
            )
            context.user_data.clear()
            return ConversationHandler.END
        incidents = [{"driver": driver, "reason": reason, "norm": norm}]

    grouped = {}
    for inc in incidents:
        r = inc["reason"]
        d = inc["driver"]
        r_id = r["id"]
        if r_id not in grouped:
            grouped[r_id] = {"reason": r, "drivers": []}
        grouped[r_id]["drivers"].append(d)

    lines = ["🔔 ИНЦИДЕНТЫ:", "Список водителей, которые не вышли на работу:"]
    for g in grouped.values():
        r = g["reason"]
        drivers = g["drivers"]
        names = ", ".join(d["name"] for d in drivers)
        if len(drivers) == 1:
            lines.append(f"- Водитель {names} не вышел. Причина – {r['name']}")
        else:
            lines.append(f"- Водители {names} не вышли. Причина – {r['name']}")

    text = "\n".join(lines)
    logger.info(
        "send_summary: user_id=%s, text=%s",
        q.from_user.id,
        text.replace("\n", " | "),
    )

    await q.message.reply_text(text)
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_Q1: [CallbackQueryHandler(handle_q1, pattern="^(q1_yes|q1_no)$")],
            STATE_FLOW: [CallbackQueryHandler(handle_step)],
        },
        fallbacks=[CommandHandler("done", done)],
    )

    app.add_handler(conv)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()