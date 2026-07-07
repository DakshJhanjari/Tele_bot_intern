# Use the official Python image
FROM python:3.11-slim

# Allow statements and log messages to immediately appear in logs
ENV PYTHONUNBUFFERED True

# Set the working directory
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Render sets PORT at runtime; default to 10000 for local Docker testing
EXPOSE 10000

# Use shell form so ${PORT} is expanded at container startup
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
