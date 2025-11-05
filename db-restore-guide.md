# ADL Database Restore Guide

Follow these steps to restore your ADL database:

## Step 1: Modify the Dockerfile

1. **Identify the correct Dockerfile**
   - The default file is `Dockerfile`
   - Check `docker-compose.yml` under the `build context` to confirm (this can be set via the `ADL_DOCKERFILE` environment variable)

2. **Edit the Dockerfile**
   - Comment out the last two lines:
     ```dockerfile
     #ENTRYPOINT ["/adl/docker-entrypoint.sh"]
     #CMD ["gunicorn-wsgi"]
     ```
   
   - Add this line:
     ```dockerfile
     CMD ["sleep", "infinity"]
     ```

## Step 2: Modify docker-compose.yml

Comment out the startup commands for three services:

1. **adl service** - Find and comment out:
   ```yaml
   #command: gunicorn wsgi
   ```

2. **adl_celery_worker service** - Comment out its command line

3. **adl_celery_beat service** - Comment out its command line

Save your changes.

## Step 3: Build the ADL Container

```bash
docker compose build adl
```

## Step 4: Start the Containers

```bash
docker compose up -d
```

## Step 5: Create PostGIS Extension

1. **Access the database container**:
   ```bash
   docker compose exec adl_db /bin/bash
   ```

2. **Connect to PostgreSQL**:
   ```bash
   psql -U <db_username> -d <db_name>
   ```
   *Replace `<db_username>` and `<db_name>` with your actual values*

3. **Create the extension**:
   ```sql
   CREATE EXTENSION postgis;
   ```

4. **Exit**:
   ```bash
   exit
   ```

## Step 6: Restore the Database

1. **Access the ADL container**:
   ```bash
   docker compose exec adl /bin/bash
   ```

2. **Run the restore command**:
   ```bash
   adl dbrestore
   ```

## Step 7: Revert Configuration Changes

```bash
git restore .
```

## Step 8: Rebuild the ADL Container

```bash
docker compose build adl
```

## Step 9: Restart Docker Compose

```bash
docker compose up -d
```

---

Your ADL database should now be successfully restored and running with the original configuration.
