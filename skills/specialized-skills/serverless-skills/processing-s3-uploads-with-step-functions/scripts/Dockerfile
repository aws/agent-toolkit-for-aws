FROM python:3.12-slim

RUN pip install --no-cache-dir boto3
RUN useradd --create-home appuser
USER appuser

WORKDIR /app
COPY fargate_processor.py .

CMD ["python", "fargate_processor.py"]
