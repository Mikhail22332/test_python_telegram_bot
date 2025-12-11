import os

from dotenv import load_dotenv

load_dotenv()

TOKEN=os.getenv('TOKEN')

COURIERS = [
    {"id": 1, "name": "Иванов"},
    {"id": 2, "name": "Петров"},
    {"id": 3, "name": "Сидоров"},
    {"id": 4, "name": "Романов"},
    {"id": 5, "name": "Дубович"},
]

REASONS = [
    {"id": 1, "name": "Дождь"},
    {"id": 2, "name": "Пожар"},
    {"id": 3, "name": "Протесты"}
]

NORMALIZATION_FACTOR = [
    {"id": 1, "name": "несколько часов"},
    {"id": 2, "name": "пару дней"},
    {"id": 3, "name": "неделя"}
]

