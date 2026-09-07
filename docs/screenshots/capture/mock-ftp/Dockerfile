# Mock FTP source for the documentation screenshot pipeline (decision 7 of
# the docs plan): serves freshly generated TOA5 sample files so a seeded FTP
# connection can run a genuine collection cycle before capture.
FROM python:3.12-alpine
RUN pip install --no-cache-dir pyftpdlib==2.0.1
WORKDIR /srv
COPY server.py /srv/server.py
EXPOSE 21 30000-30009
CMD ["python", "/srv/server.py"]
