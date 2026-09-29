FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

# ffmpeg приводит учебные записи (MP3/WAV) к формату телефонии
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-root --only main

COPY . .

EXPOSE 8001

# один процесс: состояние пула номеров и звонков хранится в памяти
CMD ["uvicorn", "arm_voip.app:app", "--host", "0.0.0.0", "--port", "8001"]
