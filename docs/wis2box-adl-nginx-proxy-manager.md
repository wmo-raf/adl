# 🌐 WIS2BOX with SSL on ADL Server

This guide explains how to configure [wis2box](https://docs.wis2box.wis.wmo.int) on the same server as ADL, enabling
SSL via Nginx Proxy Manager and internal communication between the two systems.

By placing `wis2box` and `ADL` on the same Docker network, you enable:

- Direct internal communication between wis2box and ADL services
- Centralized SSL management through Nginx Proxy Manager
- Simplified configuration without exposing unnecessary ports

## Prerequisites

- wis2box installed on the same server as ADL
- A domain name pointing to your server's IP address

## Step 1: Set Up Nginx Proxy Manager

If you have not already set up Nginx Proxy Manager, you need to do this first.

Stop wis2box before proceeding:

```shell
cd /path/to/wis2box
python3 wis2box-ctl.py stop
```

Now follow the [SSL Setup with Nginx Proxy Manager](ssl-setup-nginx-proxy-manager.md) guide to install and configure
NPM.

Once NPM is running, return here to continue with the wis2box configuration.

## Step 2: Update wis2box Docker Configuration

Open the `docker-compose.override.yml` file in your wis2box directory:

```shell
cd /path/to/wis2box
nano docker-compose.override.yml
```

Update the file with the following changes:

```yaml
services:
  web-proxy:
    ports:
      - 80

  wis2box-ui:
    ports:
      - 9999:80

  minio:
    ports:
      - "9000:9000"
      - "9001:9001"
      - "8022:8022"
    deploy:
      replicas: 1

  mosquitto:
    ports:
      - 1883:1883
      - 8884:8884

networks:
  default:
    external: true
    name: adl
```

**Key changes:**

- **web-proxy ports**: Changed from `80:80` to just `80`. This exposes port 80 only within the Docker network, not on
  the host. NPM will handle external traffic and SSL termination.
- **networks**: Added the external network configuration to connect wis2box to the same Docker network as ADL and NPM.

Replace `adl` with your network name if you used a different name in your ADL `.env` file.

## Step 3: Start wis2box

Start wis2box with the updated configuration:

```shell
python3 wis2box-ctl.py start
```

Verify that wis2box containers are running and connected to the correct network:

```shell
docker network inspect adl
```

You should see both wis2box and ADL containers listed in the network's "Containers" section.

## Step 4: Add Proxy Host in Nginx Proxy Manager

Open NPM in your browser at `http://<your-server-ip>:81` and log in.

Navigate to "Proxy Hosts" and click "Add Proxy Host".

**Details Tab:**

| Field                 | Value                    |
|-----------------------|--------------------------|
| Domain Names          | `wis2box.yourdomain.com` |
| Scheme                | `http`                   |
| Forward Hostname / IP | `web-proxy`              |
| Forward Port          | `80`                     |
| Websockets Support    | On                       |

**SSL Tab:**

- Check **SSL Certificate** and select "Request a new SSL Certificate"
- Check **Force SSL**
- Check **HTTP/2 Support**
- Agree to the Let's Encrypt Terms of Service

Click "Save" to create the proxy host.

## Step 5: Update wis2box URL Configuration

Ensure that `WIS2BOX_URL` and `WIS2BOX_API_URL` as defined in your `wis2box.env` points to the new HTTPS URL.

```shell
nano wis2box.env
```

Update the URLs:

```text
WIS2BOX_URL=https://wis2box.yourdomain.

WIS2BOX_API_URL=https://wis2box.yourdomain.com/oapi
```

After updating `WIS2BOX_URL` and `WIS2BOX_API_URL`, please stop and start wis2box using wis2box-ctl.py and republish
your
data using the command `wis2box metadata discovery republish`:

```shell
python3 wis2box-ctl.py start
python3 wis2box-ctl.py login
wis2box metadata discovery republish
```

## Verifying the Setup

1. Open `https://wis2box.yourdomain.com` in your browser
2. Verify that the connection is secure (padlock icon in the address bar)
3. Check that all wis2box functionality works correctly

## Troubleshooting

### 502 Bad Gateway

- Verify that wis2box services are running: `python3 wis2box-ctl.py status`
- Check that containers are on the same network: `docker network inspect adl`
- Ensure the Forward Hostname matches the service name in docker-compose ( `web-proxy`)

### SSL Certificate Request Fails

- Confirm DNS is properly configured for your domain
- Check that ports 80 and 443 are accessible on your server
- Review NPM logs: `docker logs nginx_proxy_manager`

### wis2box Features Not Working After SSL

- Ensure `WIS2BOX_URL` and `WIS2BOX_API_URL` are updated to use `https://`
- Check browser console for mixed content warnings

### ADL Cannot Communicate with wis2box

- Verify both stacks are on the same network: `docker network inspect adl`
- Use the service name (e.g., `web-proxy`, `minio`) when referencing wis2box services from ADL, not `localhost`
