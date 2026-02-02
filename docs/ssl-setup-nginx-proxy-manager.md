# 🔐 SSL with Nginx Proxy Manager

This guide provides instructions on how to set up SSL for your application using Nginx Proxy Manager (NPM). Nginx Proxy
Manager is a powerful tool that simplifies the process of managing Nginx proxy hosts, including SSL certificate
management.

ADL by default does not come with SSL setup. It is recommended to use Nginx Proxy Manager as a reverse proxy to handle
SSL termination.

## Prerequisites

- A domain name pointing to your server's IP address (DNS A record configured)
- Ports 80 and 443 available on your server
- Docker and Docker Compose installed

## Nginx Proxy Manager Setup

We recommend setting up NPM as a separate Docker Compose stack. This allows for better separation of concerns and easier
management when dealing with many services on the same server that might need proxying.

### 1. Change ADL Web Proxy Port

Before setting up NPM, ensure that the ADL web service is not using ports 80 or 443, as NPM will need these. Update the
`ADL_WEB_PROXY_PORT` variable in your `.env` file to use a different port, such as 8080.

From the root of the ADL directory, open the `.env` file in your preferred text editor:

```shell
nano .env
```

Find the line that sets `ADL_WEB_PROXY_PORT` and change it to:

```text
ADL_WEB_PROXY_PORT=8080
```

Or any other unused port of your choice. Save the file and exit the editor.

### 2. Install Nginx Proxy Manager

You can follow the [official Nginx Proxy Manager installation guide](https://nginxproxymanager.com/guide/) for a
detailed guide. Here, we provide a quick overview to get you started.

Below is a quick `docker-compose.yml` example to get you started with NPM:

```yaml
services:
  nginx_proxy_manager:
    image: 'jc21/nginx-proxy-manager:latest'
    container_name: nginx_proxy_manager
    restart: unless-stopped
    ports:
      - '80:80'
      - '81:81'
      - '443:443'
    volumes:
      - ./data:/data
      - ./letsencrypt:/etc/letsencrypt

networks:
  default:
    external: true
    name: ${NETWORK_NAME}
```

Create a new directory for NPM and set up the configuration files:

```shell
mkdir nginx-proxy-manager
cd nginx-proxy-manager
nano docker-compose.yml
```

Copy the above YAML content into the `docker-compose.yml` file and save it.

Create a `.env` file in the same directory with the following content:

```text
NETWORK_NAME=adl
```

This ensures that NPM is on the same Docker network as your ADL stack.

### 3. Start Nginx Proxy Manager

Run the following command to start NPM:

```shell
docker-compose up -d
```

### 4. Access and Configure Nginx Proxy Manager

Open your web browser and navigate to `http://<your-server-ip>:81`.

On first login, you will be prompted to create an admin account. Use a strong username and password.

### 5. Add a Proxy Host

After logging in, navigate to the "Proxy Hosts" section and click on "Add Proxy Host".

**Details Tab:**

- **Domain Names**: Enter your domain (e.g., `adl.yourdomain.com`)
- **Scheme**: `http`
- **Forward Hostname / IP**: `adl_web_proxy` (the container name of the ADL web proxy service)
- **Forward Port**: `80` (the internal port Nginx listens on within the container. This is `NOT the ADL_WEB_PROXY_PORT`)

**SSL Tab:**

- Check **SSL Certificate** and select "Request a new SSL Certificate"
- Check **Force SSL** to redirect all HTTP traffic to HTTPS
- Check **HTTP/2 Support** for improved performance
- Agree to the Let's Encrypt Terms of Service

Click "Save" to create the proxy host and obtain the SSL certificate.

## Troubleshooting

### SSL Certificate Request Fails

- Ensure your domain's DNS A record points to your server's public IP address
- Verify that ports 80 and 443 are open and not blocked by a firewall
- Check that no other service is using ports 80 or 443

### 502 Bad Gateway Error

- Verify that the ADL stack is running: `docker ps`
- Confirm that NPM and ADL are on the same Docker network
- Check the container name matches what you entered in "Forward Hostname / IP"
- Review NPM logs: `docker logs nginx_proxy_manager`

### Cannot Access NPM Admin Panel

- Ensure port 81 is open and accessible
- Try accessing via `http://<server-ip>:81` instead of the domain name
