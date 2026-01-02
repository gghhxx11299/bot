# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install only necessary dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Render expects app to bind to PORT (default: 10000)
# But we read it dynamically in uvicorn command
ENV PORT=10000

# Expose the port
EXPOSE $PORT

# Start the FastAPI app with dynamic port binding
CMD ["sh", "-c", "uvicorn main:fastapi_app --host 0.0.0.0 --port $PORT"]
