FROM python:3.12-slim@sha256:e5c9fa26ffb76e11e0f054f30dc2523a2f9693f0c36c0cf1e39b27e152d899fc

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
RUN useradd --create-home appuser
USER appuser

WORKDIR /app
COPY fargate_processor.py .

CMD ["python", "fargate_processor.py"]
