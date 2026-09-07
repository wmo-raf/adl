# A stand-in for a wis2box instance's station catalogue, so the WIS2Box Stations
# comparison page has all three of its tables populated during capture:
# DEMO001/DEMO002 are on both sides, DEMO003 is in ADL only (absent here), and
# DEMO900 is on wis2box only. ADL reads
# <wis2box_url>/oapi/collections/stations/items?f=json; a static file at that
# path answers it, query string and all, because the server ignores the query.
FROM python:3.12-alpine
COPY site /site
WORKDIR /site
EXPOSE 80
CMD ["python", "-m", "http.server", "80"]
