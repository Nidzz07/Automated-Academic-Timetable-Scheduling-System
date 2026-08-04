FROM python:3.12-slim

WORKDIR /app

# Installed from the repo-root requirements.txt; build context is the repo root.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
