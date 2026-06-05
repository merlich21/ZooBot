import asyncio
import logging
import random
from collections import Counter
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, ADMIN_CHAT_ID
from questions import questions
from animals import ANIMALS, ANIMAL_KEYS

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

class QuizState(StatesGroup):
    waiting_for_answer = State()
    collecting_feedback = State()

user_scores = {}          # user_id -> Counter
user_question_index = {}  # user_id -> int

def get_keyboard(options):
    buttons = []
    for i, option in enumerate(options):
        buttons.append([InlineKeyboardButton(text=option["text"], callback_data=f"answer_{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def calculate_result(scores: Counter):
    if not scores:
        return None
    max_score = max(scores.values())
    leaders = [animal for animal, score in scores.items() if score == max_score]
    return random.choice(leaders)

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    user_scores[user_id] = Counter()
    user_question_index[user_id] = 0
    await message.answer(
        "Привет! 🦁 Я бот-викторина Московского зоопарка.\n"
        "Пройди викторину и узнай, какое животное — твой тотемный покровитель.\n"
        "А ещё ты сможешь помочь зоопарку в программе опеки «Клуб друзей».\n"
        "Нажми «Начать викторину», когда будешь готов!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать викторину 🚀", callback_data="start_quiz")]
        ])
    )

@dp.callback_query(F.data == "start_quiz")
async def start_quiz(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_scores[user_id] = Counter()
    user_question_index[user_id] = 0
    await state.set_state(QuizState.waiting_for_answer)
    await ask_question(callback.message, user_id)

async def ask_question(message: Message, user_id: int):
    idx = user_question_index.get(user_id, 0)
    if idx < len(questions):
        q = questions[idx]
        keyboard = get_keyboard(q["options"])
        await message.answer(f"Вопрос {idx+1}/{len(questions)}:\n{q['question']}", reply_markup=keyboard)
    else:
        # На все вопросы дан ответ — показываем результат ровно один раз
        await show_result(message, user_id)

@dp.callback_query(F.data.startswith("answer_"), QuizState.waiting_for_answer)
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    idx = user_question_index.get(user_id, 0)
    if idx >= len(questions):
        await callback.answer("Викторина уже завершена. Нажми /start для перезапуска.")
        return
    q = questions[idx]
    answer_idx = int(callback.data.split("_")[1])
    if answer_idx < 0 or answer_idx >= len(q["options"]):
        await callback.answer("Неверный выбор")
        return

    option = q["options"][answer_idx]
    for animal, weight in option["weights"].items():
        user_scores[user_id][animal] += weight

    await callback.message.edit_reply_markup(reply_markup=None)
    user_question_index[user_id] += 1
    await ask_question(callback.message, user_id)   # ← вызовет show_result, когда нужно
    await callback.answer()

async def show_result(message: Message, user_id: int):
    scores = user_scores.get(user_id, Counter())
    if not scores:
        await message.answer("Ой, похоже ты ещё не отвечал на вопросы. Начни заново /start")
        return
    winner_key = calculate_result(scores)
    if winner_key is None:
        await message.answer("Не удалось определить тотемное животное. Попробуй ещё раз /start")
        return

    animal = ANIMALS[winner_key]

    # Полный текст с описанием и информацией об опеке
    full_text = (
        f"<b>Твоё тотемное животное — {animal['name']}!</b>\n\n"
        f"{animal['description']}\n\n"
        f"{animal['patronage_info']}"
    )

    # Отправляем изображение
    try:
        photo = FSInputFile(f"images/{animal['image']}")
        await message.answer_photo(photo, caption=full_text, parse_mode="HTML")
    except Exception:
        await message.answer(full_text + "\n\n(изображение не найдено, но это не страшно 😉)", parse_mode="HTML")

    me = await bot.me()
    bot_username = me.username

    # Клавиатура с действиями выводится ОДИН раз
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Узнать о программе опеки", callback_data="patronage_info")],
        [InlineKeyboardButton(text="📤 Поделиться результатом",
                              switch_inline_query=f"Моё тотемное животное — {animal['name']}! Узнай своего: @{bot_username}")],
        [InlineKeyboardButton(text="📞 Связаться с сотрудником", callback_data="contact")],
        [InlineKeyboardButton(text="📝 Оставить отзыв", callback_data="feedback")],
        [InlineKeyboardButton(text="🔄 Попробовать ещё раз", callback_data="start_quiz")]
    ])
    await message.answer("Что хочешь сделать дальше?", reply_markup=keyboard)

@dp.callback_query(F.data == "patronage_info")
async def patronage_info(callback: types.CallbackQuery):
    msg = ("<b>Программа опеки «Клуб друзей»</b>\n\n"
           "Вы можете взять под опеку любого обитателя Московского зоопарка и помогать заботиться о нём. "
           "Средства идут на питание, обогащение среды и ветеринарное обслуживание.\n"
           "Опека доступна как частным лицам, так и организациям.\n"
           "Узнайте подробнее на официальном сайте: https://moscowzoo.ru/about/guardianship\n"
           "Спасибо, что помогаете сохранить биоразнообразие! 🌍")
    await callback.message.answer(msg, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()

@dp.callback_query(F.data == "contact")
async def contact(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    scores = user_scores.get(user_id, Counter())
    if scores:
        winner_key = calculate_result(scores)
        if winner_key:
            animal_name = ANIMALS[winner_key]["name"]
            winner_score = scores[winner_key]
            result_text = (
                f"Пользователь @{callback.from_user.username} (id: {user_id}) "
                f"получил тотем: {animal_name}.\n"
                f"Баллы: {winner_score}"
            )
        else:
            result_text = f"Пользователь @{callback.from_user.username} (id: {user_id}) получил тотем: неизвестно."
    else:
        result_text = f"Пользователь @{callback.from_user.username} ещё не прошёл викторину."
    try:
        await bot.send_message(ADMIN_CHAT_ID, f"Запрос на связь:\n{result_text}")
        await callback.message.answer(
            "Сотрудник зоопарка скоро свяжется с вами. 📩\n"
            "Пока можете также написать на почту: zoofriends@moscowzoo.ru"
        )
    except Exception as e:
        await callback.message.answer("Не удалось отправить запрос. Пожалуйста, напишите на почту zoofriends@moscowzoo.ru")
    await callback.answer()

@dp.callback_query(F.data == "feedback")
async def ask_feedback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(QuizState.collecting_feedback)
    await callback.message.answer("Пожалуйста, напишите ваш отзыв одним сообщением. Я передам его сотрудникам зоопарка.")
    await callback.answer()

@dp.message(QuizState.collecting_feedback)
async def collect_feedback(message: Message, state: FSMContext):
    user_id = message.from_user.id
    feedback = message.text
    with open("feedback.txt", "a", encoding="utf-8") as f:
        f.write(f"User {user_id}: {feedback}\n")
    await message.answer("Спасибо за ваш отзыв! 🦒 Мы стали лучше благодаря вам.")
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())