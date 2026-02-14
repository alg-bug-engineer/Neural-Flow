FROM python:latest
WORKDIR /app
ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY libs ./libs
COPY services ./services
COPY config ./config
COPY data ./data
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
