FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY run.py .
RUN mkdir -p data uploads
EXPOSE 8080
CMD ["sh", "-c", "python scripts/init_db.py && exec gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --access-logfile - 'app:create_app()'"]
