FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py .

RUN useradd --system --no-create-home jobmail
USER jobmail

EXPOSE 8000
# One worker + threads: schema creation at start-up runs once; the app is I/O bound.
CMD ["sh", "-c", "exec gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120 --access-logfile -"]
