# Airflow 3.3.2 + thu vien cua luong du lieu.
#
# Image Airflow chinh thuc DA CO SAN "ODBC Driver 18 for SQL Server", unixodbc va pyodbc,
# nen khong can (va khong nen) cai lai: khai bao trung kho phan mem cua Microsoft se gay loi
# "Conflicting values set for option Signed-By".
FROM apache/airflow:3.3.2

USER airflow
COPY airflow/requirements-airflow.txt /tmp/requirements-airflow.txt
# Giu nguyen phien ban Airflow khi cai them thu vien (khuyen nghi cua Airflow)
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /tmp/requirements-airflow.txt

# Tu kiem tra: build se dung lai o day neu image thieu driver hoac thu vien can thiet
RUN python -c "import sys, pyodbc, pandas, pyarrow; d = pyodbc.drivers(); print('ODBC drivers:', d); print('pandas', pandas.__version__, '| pyarrow', pyarrow.__version__); sys.exit(0 if 'ODBC Driver 18 for SQL Server' in d else 'THIEU ODBC Driver 18 for SQL Server')"
