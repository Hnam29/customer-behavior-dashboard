# Dashboard Streamlit chay trong Docker (image Python gon nhe, khong can Airflow).
# Ma nguon va thu muc data duoc gan tu may vao /app luc chay (xem docker-compose.yaml),
# nen sua app.py / core / pipeline khong can build lai.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY dashboard/requirements-dashboard.txt /tmp/requirements-dashboard.txt
RUN pip install -r /tmp/requirements-dashboard.txt

WORKDIR /app
EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--browser.gatherUsageStats=false", "--server.fileWatcherType=poll"]
