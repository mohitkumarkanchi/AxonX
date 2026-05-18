# 🐳 AxonX Local Development & Testing Dockerfile
FROM python:3.11-slim

# Install system dependencies required for compiling native tree-sitter bindings and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside container
WORKDIR /app

# Copy only pyproject.toml and README.md first to leverage Docker's layer cache for package installation
COPY pyproject.toml README.md ./

# Upgrade pip and install the project in editable/development mode along with dev/test tools
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

# Copy the application source code
COPY agent/ ./agent/

# Expose port 7070 for the AxonX local HTTP + SSE server
EXPOSE 7070

# Default action is to serve the application for the mounted workspace
CMD ["python", "-m", "agent.cli", "serve", "--workspace", "/app", "--port", "7070"]
