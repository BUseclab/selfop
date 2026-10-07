FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Core dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    sudo \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    jq \
    ca-certificates \
    gnupg \
    ripgrep \
    dnsutils \
    iproute2 \
    less \
    procps \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 24 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Codex CLI
RUN npm install -g @openai/codex

# Create a non-root user (Codex CLI may also refuse auto-approve as root)
RUN useradd -m -s /bin/bash agent && \
    echo "agent ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Create working directories
RUN mkdir -p /task-run /app && \
    chown -R agent:agent /task-run /app

# Copy necessary files and make executable
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

# Create the codex home directory
RUN mkdir -p /home/agent/.codex && chmod -R 777 /home/agent

# Set the user to the non-root user
USER agent

# Set the working directory
WORKDIR /task-run
ENTRYPOINT ["/app/run.sh"]
